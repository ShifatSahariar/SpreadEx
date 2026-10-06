"""The measurement produced by running one input against one target.

An Observation carries NO judgement. Deciding whether `exit_code == 1` means
"bug" or "this input was correctly rejected" is the Oracle's job -- for a parser
or compiler a non-zero exit is usually the *correct* behaviour.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from typing import Any

PREVIEW_CHARS = 2000
#: How much of the END of stderr a failure signature is computed from. Generous on purpose: frames
#: carry absolute paths, so a signature computed from a short excerpt would depend on how deep the
#: project folder sits. Not stored with the execution; it only feeds the oracle.
SIGNATURE_TAIL_CHARS = 20000


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class Observation:
    """What happened when one input met one target. Facts only."""

    input_hash: str
    sut_id: str
    sut_version: str | None

    exit_code: int | None
    signal: int | None
    timed_out: bool

    duration_ms: float

    stdout_hash: str
    stderr_hash: str
    stdout_preview: str | None
    stderr_preview: str | None
    #: The last SIGNATURE_TAIL_CHARS of stderr, for failure signatures (see above).
    stderr_tail: str | None = None

    @property
    def crashed_by_signal(self) -> bool:
        return self.signal is not None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def preview(s: str | None) -> str | None:
    """Keep a bounded, human-readable head of a stream for triage."""
    if not s:
        return None
    s = s.strip()
    if len(s) <= PREVIEW_CHARS:
        return s
    # Head AND tail: a Python traceback ends with the innermost frames and the exception itself,
    # so keeping only the head made a crash's signature depend on how much fitted before the cut --
    # which a longer project path changes.
    half = PREVIEW_CHARS // 2
    return s[:half] + f"\n... [{len(s) - 2 * half} chars omitted] ...\n" + s[-half:]
