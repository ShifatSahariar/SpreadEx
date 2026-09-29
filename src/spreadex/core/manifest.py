"""Campaign manifest: enough to replay a run somewhere else.

This is what makes a result checkable by someone who was not there, and it is
the cheapest route to an artifact-evaluation badge.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = "1"


@dataclass
class Manifest:
    run_id: str
    spreadex_version: str
    manifest_version: str = MANIFEST_VERSION
    config_hash: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    seed: int = 42
    signal: str = "cc"
    targets: list[dict[str, Any]] = field(default_factory=list)
    effective: dict[str, Any] = field(default_factory=dict)  # post-CLI-override values
    corpus: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    def hash(self) -> str:
        """Hash of everything that determines the run, excluding its results."""
        payload = {k: v for k, v in asdict(self).items()
                   if k not in ("results", "started_at", "finished_at", "environment")}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=False))
        return path

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        return cls(**json.loads(Path(path).read_text()))


def capture_environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "java": _probe(["java", "-version"]),
        "git_commit": _probe(["git", "rev-parse", "HEAD"]),
    }


def probe_target_version(command: list[str]) -> str | None:
    """Best-effort version string for a SUT, so replays can detect drift."""
    if not command:
        return None
    for flag in ("--version", "-version", "-v"):
        out = _probe([command[0], flag])
        if out:
            return out
    return None


def _probe(cmd: list[str]) -> str | None:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
        text = (p.stdout or b"").decode(errors="replace") or (p.stderr or b"").decode(errors="replace")
        first = text.strip().splitlines()
        return first[0].strip() if first else None
    except (OSError, subprocess.SubprocessError):
        return None
