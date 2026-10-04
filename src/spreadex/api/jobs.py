"""One background job at a time, with a log the UI can poll.

The wizard needs to install a generator and launch a campaign -- both slow,
both code-executing. Allowing exactly one at a time keeps the model simple
enough to reason about: there is never a question of which run a log line
belongs to, and two campaigns cannot race over the same corpus.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_LINES = 500


@dataclass
class Job:
    kind: str                       # "run" | "install"
    label: str
    lines: list[str] = field(default_factory=list)
    done: bool = False
    ok: bool | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, line: str) -> None:
        with self._lock:
            self.lines.append(str(line))
            if len(self.lines) > MAX_LINES:
                del self.lines[: len(self.lines) - MAX_LINES]

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self._lock:
            return {
                "kind": self.kind,
                "label": self.label,
                "done": self.done,
                "ok": self.ok,
                "error": self.error,
                "result": self.result,
                "lines": self.lines[since:],
                "total_lines": len(self.lines),
            }


class JobRunner:
    """Holds at most one job. A finished job stays readable until replaced."""

    def __init__(self) -> None:
        self._job: Job | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def current(self) -> Job | None:
        return self._job

    @property
    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, kind: str, label: str, work: Callable[[Job], dict]) -> Job:
        with self._lock:
            if self.busy:
                raise RuntimeError(
                    f"{self._job.label!r} is still running. Wait for it to finish."
                )
            job = Job(kind=kind, label=label)
            self._job = job

            def target():
                try:
                    job.result = work(job) or {}
                    job.ok = True
                except Exception as exc:  # noqa: BLE001 - surfaced to the user
                    job.ok = False
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.log(job.error)
                    for line in traceback.format_exc().splitlines()[-6:]:
                        job.log(line)
                finally:
                    job.done = True

            self._thread = threading.Thread(target=target, daemon=True)
            self._thread.start()
            return job
