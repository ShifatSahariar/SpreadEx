"""A local, read-only HTTP server for the SpreadEx UI.

Bound to the loopback interface and built on the standard library, so
`spreadex ui` needs no extra install and nothing is uploaded anywhere.

A localhost bind is NOT an authentication boundary: any page the user visits
can issue requests to 127.0.0.1, and DNS rebinding defeats naive Origin checks.
Four controls, in order of what actually stops what:

1. a random per-session token required on EVERY request, not just the first
   page load (Jupyter's model);
2. strict Host header validation -- this, not Origin checking, is what defeats
   DNS rebinding;
3. a Content-Security-Policy that forbids loading anything off-machine;
4. loopback by default, with --host deliberate and loud.

WRITE ACCESS. The setup wizard creates `spreadex.yaml` and launches campaigns,
so the UI is no longer read-only and the browser can now cause code to run.
Three things keep that honest:

- every mutating route is POST and takes its token from a HEADER, never the
  query string. A cross-origin form cannot set a custom header, and no CORS
  headers are ever sent, so a hostile page cannot reach these routes at all;
- the command a campaign will execute is the one the user just reviewed and
  wrote to `spreadex.yaml`; the server never synthesises a command;
- `--read-only` restores the previous posture, with every POST refused.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import data
from .jobs import JobRunner

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}

CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class _Handler(BaseHTTPRequestHandler):
    server_version = "SpreadEx"
    sys_version = ""

    # -------------------------------------------------------------- plumbing

    @property
    def config(self):
        return self.server.spreadex_config

    def log_message(self, fmt, *args):
        if self.server.spreadex_verbose:
            super().log_message(fmt, *args)

    def _send(self, status, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, status=HTTPStatus.OK) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _error(self, status, message: str) -> None:
        self._json({"error": message}, status)

    # ------------------------------------------------------------- security

    def _host_is_local(self) -> bool:
        host = self.headers.get("Host", "")
        hostname = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") else host
        return hostname.strip("[]") in {h.strip("[]") for h in ALLOWED_HOSTNAMES}

    def _has_corpus(self) -> bool:
        """True once there is something to read.

        The real invariant is "a corpus exists", not "a config exists" -- which
        also stops a configured-but-never-run project from having `.spreadex/`
        materialised just by opening the UI.
        """
        return self.config.state_dir.is_dir()

    def _token_ok(self, query) -> bool:
        supplied = (self.headers.get("X-SpreadEx-Token")
                    or (query.get("token", [""])[0] if query else ""))
        return secrets.compare_digest(supplied or "", self.server.spreadex_token)

    # --------------------------------------------------------------- routing

    def _reject_non_local(self) -> bool:
        if self._host_is_local():
            return False
        # A request whose Host is not a loopback name reached us through
        # someone else's DNS: refuse before looking at anything else.
        self._error(HTTPStatus.FORBIDDEN, "non-local Host header refused")
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        # Read the body FIRST, whatever the verdict. On a keep-alive connection
        # an unread body stays in the socket and desynchronises the next
        # request, so a rejected POST would break the request after it.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            # Discard (never store) what was sent, so the client sees the 413 instead of a
            # broken pipe; give up and close if it is absurdly large.
            left = min(length, MAX_DRAIN)
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "that request is too large")
            return
        raw = self.rfile.read(length) if length else b""

        if self._reject_non_local():
            return
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        # A mutating route accepts the token only from a header. A cross-origin
        # form can POST, but it cannot set a custom header without a CORS
        # preflight that this server never answers.
        header_token = self.headers.get("X-SpreadEx-Token") or ""
        if not secrets.compare_digest(header_token, self.server.spreadex_token):
            self._error(HTTPStatus.UNAUTHORIZED, "missing or invalid token header")
            return
        if self.server.spreadex_read_only:
            self._error(HTTPStatus.FORBIDDEN,
                        "this UI was started with --read-only; it cannot change anything")
            return

        try:
            body = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "body must be JSON")
            return

        try:
            self._route_post(route, body)
        except Exception as exc:  # noqa: BLE001 - a view must not kill the server
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def _route_post(self, route: str, body: dict) -> None:
        from . import setup

        if route == "/api/config":
            result = setup.save_config(self.config, body)
            if result.get("written"):
                reload_project(self.server)
            self._json(result)
            return
        if route == "/api/probe":
            # A POST, and so already behind the header-only token and refused
            # under --read-only: this runs the command the user just typed.
            self._json(setup.probe_target(self.config, body))
            return
        if route == "/api/generators/install":
            self._json(setup.start_install(self.server, body))
            return
        if route == "/api/run":
            self._json(setup.start_run(self.server, body))
            return
        if route == "/api/assist":
            if not getattr(self.server, "spreadex_experimental", False):
                self._error(HTTPStatus.FORBIDDEN,
                            "the grammar assistant is experimental and off by default; "
                            "restart with `spreadex ui --experimental` to enable it")
                return
            self._json(setup.assist(self.config, body))
            return
        if route == "/api/spec/extract":
            self._json(setup.extract_document(self.config, body))
            return
        if route == "/api/spec/save":
            self._json(setup.save_spec(self.config, body))
            return
        if route == "/api/grammar/save":
            self._json(setup.save_grammar(self.config, body))
            return
        self._error(HTTPStatus.NOT_FOUND, f"no route {route!r}")

    def do_GET(self):
        if self._reject_non_local():
            return

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path.rstrip("/") or "/"

        # The static shell carries no project data and needs no token. Gating it
        # too would make a plain page refresh impossible, because the token is
        # deliberately stripped from the address bar after first load -- the
        # page could never get far enough to present the token it already holds.
        # Every /api/ route, which is where the data lives, still requires it.
        if route.startswith("/api/") and not self._token_ok(query):
            self._error(HTTPStatus.UNAUTHORIZED,
                        "missing or invalid token; open the URL printed by `spreadex ui`")
            return

        try:
            self._route(route, query)
        except Exception as exc:  # noqa: BLE001 - a view must not kill the server
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    def _route(self, route: str, query) -> None:
        state_dir = self.config.state_dir

        if route in ("/", "/index.html"):
            self._static("index.html")
            return
        if route.startswith("/static/"):
            self._static(route[len("/static/"):])
            return

        if route == "/api/project":
            self._json({
                "configured": self.config.configured,
                "read_only": self.server.spreadex_read_only,
                "root": str(self.config.project_root),
                "targets": [{"name": t.name, "command": t.command} for t in self.config.targets],
                "generators": list(self.config.generators or []),
                "differential": self.config.is_differential,
                "signal": self.config.signal,
                "oracle": self.config.oracle.get("type"),
                "experimental": getattr(self.server, "spreadex_experimental", False),
                # Can a run write its results? The review screen's Storage check. Looks at the state
                # directory if it exists, otherwise at the project folder that would contain it.
                "writable": _can_write(self.config.state_dir),
            })
            return
        if route == "/api/runs":
            self._json({"runs": data.list_runs(state_dir) if self._has_corpus() else []})
            return
        if route.startswith("/api/runs/"):
            run_id = route[len("/api/runs/"):]
            detail = data.run_detail(state_dir, run_id) if self._has_corpus() else None
            if detail is None:
                self._error(HTTPStatus.NOT_FOUND, f"no run {run_id!r}")
                return
            self._json(detail)
            return
        if route == "/api/input":
            blob = (query.get("hash") or [""])[0]
            if not blob.isalnum():
                self._error(HTTPStatus.BAD_REQUEST, "bad hash")
                return
            payload = data.input_text(state_dir, blob) if self._has_corpus() else None
            if payload is None:
                self._error(HTTPStatus.NOT_FOUND, "no such input")
                return
            self._json(payload)
            return
        if route == "/api/spec":
            from . import setup
            self._json(setup.read_spec(self.config))
            return
        if route == "/api/grammars/bundled":
            from . import setup
            self._json(setup.bundled_grammars())
            return
        if route == "/api/grammar":
            source = (query.get("source") or [None])[0]
            self._json(data.grammar_report(self.config, source))
            return
        if route == "/api/config":
            from . import setup
            self._json(setup.read_config(self.config))
            return
        if route == "/api/generators":
            from . import setup
            self._json(setup.generator_status(self.config))
            return
        if route == "/api/activity":
            since = int((query.get("since") or ["0"])[0] or 0)
            job = self.server.spreadex_jobs.current
            self._json(job.snapshot(since) if job else {"idle": True})
            return
        if route == "/api/files":
            from . import setup
            self._json(setup.list_candidate_grammars(self.config))
            return
        if route == "/api/providers":
            from . import setup
            if not getattr(self.server, "spreadex_experimental", False):
                self._json({"providers": [], "experimental": False})
                return
            self._json({**setup.llm_providers(), "experimental": True})
            return

        if route.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, f"no route {route!r}")
            return
        # A person typed a path into the address bar. A JSON 404 helps nobody;
        # send them to the one page there is. (/spreadex, for instance, was a
        # route in the older research webapp.)
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()

    def _static(self, name: str) -> None:
        # Resolve inside STATIC_DIR so a crafted path cannot escape it.
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind.endswith(("javascript", "json")):
            kind += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), kind)


def _emit(line: str = "") -> None:
    """Print and flush: the URL has to appear before the server blocks, even
    when stdout is a pipe rather than a terminal."""
    import sys

    print(line, flush=True, file=sys.stdout)


def _can_write(state_dir) -> bool:
    import os
    from pathlib import Path

    p = Path(state_dir)
    while not p.exists() and p != p.parent:
        p = p.parent
    return os.access(p, os.W_OK | os.X_OK)


TOKEN_FILE = "ui-token"
#: Uploads travel as base64 JSON; 5 MB of document is ~6.7 MB on the wire.
MAX_BODY = 12_000_000
MAX_DRAIN = 64_000_000


def project_token(config, rotate: bool = False) -> str:
    """A token that survives restarts, so the UI has a URL worth bookmarking.

    A fresh token per launch meant the address changed every time and nothing
    could be saved. The token is kept per project in `.spreadex/ui-token`, owner
    readable only, inside a directory `spreadex init` already git-ignores.

    The trade is deliberate: a token on disk is readable by anything already
    running as this user, which is a much smaller problem than the alternatives
    -- no token at all, or a URL nobody can keep. `--new-token` rotates it, and
    the file can simply be deleted.
    """
    if not config.configured:
        # Nothing on disk yet, and nothing should be: someone who opens the UI
        # in the wrong directory and closes it must leave no trace. The token
        # is persisted by reload_project() the moment a project exists.
        return secrets.token_urlsafe(32)

    path = config.state_dir / TOKEN_FILE
    if not rotate and path.is_file():
        existing = path.read_text().strip()
        if existing:
            return existing
    return persist_token(config, secrets.token_urlsafe(32))


def persist_token(config, token: str) -> str:
    """Write a token to `.spreadex/ui-token`, owner-readable only."""
    from ..corpus import ensure_state_dir

    ensure_state_dir(config.state_dir)
    path = config.state_dir / TOKEN_FILE
    path.write_text(token)
    try:
        path.chmod(0o600)
    except OSError:
        pass   # a filesystem without POSIX modes; the directory still guards it
    return token


def reload_project(server) -> None:
    """Adopt a spreadex.yaml the wizard just wrote, without a restart.

    The rebind is a single attribute assignment, so no lock is needed under
    ThreadingHTTPServer: a request already in flight simply finishes against
    the Config it started with.
    """
    from ..core.config import ConfigError, find_config, load_config

    previous = server.spreadex_config
    path = find_config(previous.project_root)
    if path is None:
        return
    try:
        config = load_config(path)
    except ConfigError:
        return          # keep serving the old view; the POST already reported why
    server.spreadex_config = config
    if not previous.configured:
        persist_token(config, server.spreadex_token)


def serve(config, host: str = "127.0.0.1", port: int = 8777,
          open_browser: bool = True, verbose: bool = False,
          read_only: bool = False, new_token: bool = False, experimental: bool = False,
          token: str | None = None, log=_emit) -> None:
    """Run the UI until interrupted. Foreground on purpose.

    A foreground server cannot be orphaned, cannot collide with a forgotten
    instance, and leaves no "which server am I looking at?" question -- the
    problems `jupyter server list` exists to solve.
    """
    token = token or project_token(config, rotate=new_token)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = token
    httpd.spreadex_verbose = verbose
    httpd.spreadex_read_only = read_only
    # The grammar assistant is the one feature that leaves this machine, and
    # the one with no evaluation behind it. v0.1 is deterministic and offline
    # unless someone opts in on the command line.
    httpd.spreadex_experimental = experimental
    httpd.spreadex_jobs = JobRunner()
    actual_port = httpd.server_address[1]

    shown_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    plain = f"http://{shown_host}:{actual_port}"
    url = f"{plain}/?token={token}"
    log(f"\nSpreadEx UI for {config.project_root}\n")
    # Print the link that works. Leading with the bare address looked tidier but
    # sent people to a URL that cannot authorise a tab: opening it in a tab that
    # still holds the token of a previous launch gives "token out of date".
    log(f"  Open this link (it carries this session's access token):\n  {url}\n")
    log(f"  Bare address {plain} only works in a tab that was already opened from this link.\n")
    if config.configured:
        log("  Same address every time, so it is worth bookmarking.")
        log("  Rotate the token with --new-token if you ever need to.")
    else:
        log("  No spreadex.yaml here yet -- the UI will walk you through making one.")
        log("  Nothing is written to this directory until you save.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        log(f"  ! Listening on {host}, not just this machine. Anyone who can reach\n"
            f"    this port and has the token can read this project's corpus.\n")
    if read_only:
        log("  Read-only: this UI cannot change anything.")
    else:
        log("  This UI can edit spreadex.yaml and launch campaigns, which runs")
        log("  your system under test. Start it with --read-only to forbid that.")
    log("  Press Ctrl-C to stop.\n")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped")
    finally:
        httpd.server_close()
