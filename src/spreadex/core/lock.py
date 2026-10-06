"""One campaign per project at a time, across processes.

The OS lock (`flock` on `.spreadex/run.lock`) is the only thing that says a run
is active: it is released by the kernel when the holder exits, crash or not, so
a stale file can never block anyone. The JSON written inside is metadata only --
which run, which process, started from where -- for status display and for
marking a crashed run as aborted.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

LOCK_NAME = "run.lock"


class RunInProgress(RuntimeError):
    def __init__(self, info: dict | None) -> None:
        self.info = info or {}
        rid = self.info.get("run_id") or "another campaign"
        super().__init__(
            f"A campaign is already running in this project ({rid}).\n"
            "  Fix: wait for it, or stop it with `spreadex runs cancel "
            f"{self.info.get('run_id', '<id>')}`."
        )


def _path(state_dir: Path) -> Path:
    return Path(state_dir) / LOCK_NAME


def _read(path: Path) -> dict | None:
    try:
        text = path.read_text()
        return json.loads(text) if text.strip() else None
    except (OSError, ValueError):
        return None


class RunLock:
    """Held for the lifetime of one campaign. Not re-entrant."""

    def __init__(self, state_dir: Path) -> None:
        self.path = _path(state_dir)
        self._fd: int | None = None

    def acquire(self, origin: str = "cli") -> dict | None:
        """Take the lock. Returns the metadata a previous holder left behind
        (its process is gone, or we could not have the lock), so the caller can
        mark that run aborted; raises RunInProgress if the lock is held."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RunInProgress(_read(self.path)) from None
        self._fd = fd
        previous = _read(self.path)
        self._write({"run_id": None, "pid": os.getpid(), "host": socket.gethostname(),
                     "origin": origin,
                     "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return previous

    def set_run(self, run_id: str) -> None:
        info = _read(self.path) or {}
        info["run_id"] = run_id
        self._write(info)

    def _write(self, info: dict) -> None:
        assert self._fd is not None
        data = json.dumps(info).encode()
        os.ftruncate(self._fd, 0)
        os.pwrite(self._fd, data, 0)

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            os.ftruncate(self._fd, 0)  # metadata of a finished run must not look current
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def active_run(state_dir: Path) -> dict | None:
    """Metadata of the campaign running now, or None. Decided by the OS lock:
    if we can take it, nobody holds it, whatever the file says."""
    path = _path(state_dir)
    if not path.exists():
        return None
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return _read(path) or {}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def cancel_file(state_dir: Path, run_id: str) -> Path:
    return Path(state_dir) / "runs" / run_id / "cancel"
