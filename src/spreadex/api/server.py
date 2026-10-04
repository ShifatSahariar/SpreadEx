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

The server reads `.spreadex/` and never starts, stops or alters a campaign.
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

    def _token_ok(self, query) -> bool:
        supplied = (self.headers.get("X-SpreadEx-Token")
                    or (query.get("token", [""])[0] if query else ""))
        return secrets.compare_digest(supplied or "", self.server.spreadex_token)

    # --------------------------------------------------------------- routing

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_is_local():
            # A request whose Host is not a loopback name reached us through
            # someone else's DNS: refuse before looking at anything else.
            self._error(HTTPStatus.FORBIDDEN, "non-local Host header refused")
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
                "root": str(self.config.project_root),
                "targets": [{"name": t.name, "command": t.command} for t in self.config.targets],
                "generators": list(self.config.generators or []),
                "differential": self.config.is_differential,
                "signal": self.config.signal,
                "oracle": self.config.oracle.get("type"),
            })
            return
        if route == "/api/runs":
            self._json({"runs": data.list_runs(state_dir)})
            return
        if route.startswith("/api/runs/"):
            run_id = route[len("/api/runs/"):]
            detail = data.run_detail(state_dir, run_id)
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
            payload = data.input_text(state_dir, blob)
            if payload is None:
                self._error(HTTPStatus.NOT_FOUND, "no such input")
                return
            self._json(payload)
            return
        if route == "/api/grammar":
            self._json(data.grammar_report(self.config))
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


def serve(config, host: str = "127.0.0.1", port: int = 8777,
          open_browser: bool = True, verbose: bool = False, log=_emit) -> None:
    """Run the UI until interrupted. Foreground on purpose.

    A foreground server cannot be orphaned, cannot collide with a forgotten
    instance, and leaves no "which server am I looking at?" question -- the
    problems `jupyter server list` exists to solve.
    """
    token = secrets.token_urlsafe(32)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = token
    httpd.spreadex_verbose = verbose
    actual_port = httpd.server_address[1]

    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{actual_port}/?token={token}"
    log(f"\nSpreadEx UI for {config.project_root}\n")
    log(f"  {url}\n")
    if host not in ("127.0.0.1", "localhost", "::1"):
        log(f"  ! Listening on {host}, not just this machine. Anyone who can reach\n"
            f"    this port and has the token can read this project's corpus.\n")
    log("  Read-only: the UI never starts or changes a campaign.")
    log("  Press Ctrl-C to stop.\n")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\nstopped")
    finally:
        httpd.server_close()
