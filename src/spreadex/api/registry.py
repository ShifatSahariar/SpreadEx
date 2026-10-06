"""Which Workbench is running for which project, on which port, with which token.

A developer should type `spreadex` in a project and get that project's Workbench -- not think about
ports. Three things make that true, and they live here, in the user's home directory rather than in
the project (so opening the UI in the wrong folder still leaves nothing behind in it):

* a **stable preferred port per project**, derived from its path, so each project keeps its address
  and two projects rarely compete; a busy port just means the next free one;
* a **stable token per project**, so a restart, a second tab or a bookmark does not go stale;
* a **list of running servers**, so running `spreadex ui` twice reopens the first one, and
  `spreadex ui --list` / `--stop` can see them all.

Nothing here is a security boundary: the token is still required on every request, and the
registry only records where to find a server the user already started.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import signal
import socket
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_PORT = 8777
PORT_SPAN = 100          # 8777..8876: a range a firewall rule or a bookmark can live with


def home() -> Path:
    return Path(os.environ.get("SPREADEX_HOME") or (Path.home() / ".spreadex"))


def project_key(root: Path) -> str:
    return hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()


def preferred_port(root: Path) -> int:
    """Where this project's Workbench wants to live. Deterministic, so it is the same every time."""
    return BASE_PORT + int(project_key(root)[:8], 16) % PORT_SPAN


def candidate_ports(root: Path, requested: int | None = None) -> list[int]:
    """Ports to try, in order. An explicit request is honoured alone: if the user named a port and it
    is taken, that is an error to report, not something to quietly route around."""
    if requested:
        return [requested]
    first = preferred_port(root) - BASE_PORT
    return [BASE_PORT + (first + i) % PORT_SPAN for i in range(PORT_SPAN)] + [0]   # 0: let the OS choose


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


# ------------------------------------------------------------------ tokens

def _token_path(root: Path) -> Path:
    return home() / "tokens" / project_key(root)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def token_for(root: Path, rotate: bool = False) -> str:
    """This project's token: created once, then the same until rotated."""
    path = _token_path(root)
    if not rotate:
        try:
            existing = path.read_text().strip()
            if existing:
                return existing
        except OSError:
            pass
    token = secrets.token_urlsafe(32)
    _write_private(path, token)
    return token


def remember_token(root: Path, token: str) -> None:
    """Mirror a token that already exists elsewhere (a project's own ui-token) so both agree."""
    if token and not _token_path(root).is_file():
        _write_private(_token_path(root), token)


# ----------------------------------------------------------------- servers

def _prefs_path() -> Path:
    return home() / "prefs.json"


def prefs() -> dict:
    """Per-user Workbench preferences, shared by every project on this machine."""
    try:
        data = json.loads(_prefs_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_pref(key: str, value) -> None:
    data = prefs()
    data[key] = value
    _write_private(_prefs_path(), json.dumps(data, indent=2))


def _servers_path() -> Path:
    return home() / "servers.json"


def _read() -> dict:
    try:
        data = json.loads(_servers_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    _write_private(_servers_path(), json.dumps(data, indent=2))


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True            # exists, owned by someone else
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def register(root: Path, port: int, host: str = "127.0.0.1", pid: int | None = None,
             embedded_in: Path | None = None) -> None:
    """`embedded_in`: this Workbench is served from inside another one's process (the guided demo),
    so stopping it means stopping that one -- `stop` refuses rather than kill the wrong thing."""
    data = _read()
    entry = {"pid": pid or os.getpid(), "port": port, "host": host}
    if embedded_in is not None:
        entry["embedded_in"] = str(Path(embedded_in).resolve())
    data[str(Path(root).resolve())] = entry
    _write(data)


def unregister(root: Path, pid: int | None = None) -> None:
    data = _read()
    key = str(Path(root).resolve())
    entry = data.get(key)
    if entry and (pid is None or entry.get("pid") == pid):
        data.pop(key, None)
        _write(data)


def probe(entry: dict, root: Path, token: str, timeout: float = 1.0) -> bool:
    """Is that port really serving THIS project? A pid can be reused and a port can be taken over;
    asking the server who it is settles it."""
    req = Request(f"http://{entry.get('host', '127.0.0.1')}:{entry['port']}/api/project",
                  headers={"X-SpreadEx-Token": token})
    try:
        with urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except (URLError, OSError, ValueError):
        return False
    return str(Path(body.get("root", "")).resolve()) == str(Path(root).resolve())


def live_servers() -> list[dict]:
    """Running servers, with dead entries pruned from the file as a side effect."""
    data, keep, out = _read(), {}, []
    for root, entry in data.items():
        if isinstance(entry, dict) and pid_alive(entry.get("pid")):
            keep[root] = entry
            out.append({"root": root, **entry})
    if keep != data:
        _write(keep)
    return sorted(out, key=lambda e: e["root"])


def find_live(root: Path) -> dict | None:
    for e in live_servers():
        if e["root"] == str(Path(root).resolve()) and probe(e, root, token_for(root)):
            return e
    return None


class Embedded(RuntimeError):
    """The Workbench runs inside another's process; its pid is that one's."""


def stop(root: Path) -> bool:
    e = find_live(root)
    if not e:
        return False
    if e.get("embedded_in"):
        raise Embedded(e["embedded_in"])
    try:
        os.kill(e["pid"], signal.SIGTERM)
    except OSError:
        return False
    unregister(root, e["pid"])
    return True
