"""Failure-signature normalization and bucketing.

Lifted from research/MUT_KILLING_PROFILE/Mutation_Killing_Profile.py so there is
exactly one implementation shared by the tool and the research scripts.

IMPORTANT: a bucket is a *signature*, not a bug. Igor (Jiang et al., CCS'21)
measured standard stack-hash heuristics inflating bug counts by at least an
order of magnitude. Report "N signatures"; never "N unique bugs".
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

NO_EXCEPTION = "<no_exception>"

_JAVA_IN_THREAD = re.compile(r'Exception in thread ".*?" ([\w.$]+)(?::\s*(.*))?')
_JAVA_CAUSED_BY = re.compile(r"Caused by:\s+([\w.$]+)(?::\s*(.*))?")
_ANTLR_DIAG = re.compile(r"line\s+\d+:\d+\s+.+")
_EXC_TYPE = re.compile(r"([A-Za-z_]\w*(?:Exception|Error|Panic|Fault))")
_GENERIC_EXC_LINE = re.compile(
    r"^([A-Za-z_][\w.$]*(?:Exception|Error|Panic|Fault))(?::\s*(.*))?$"
)
_FRAME_JAVA = re.compile(r"^\s*at\s+([\w.$<>]+)\(")
# CPython: '  File "/path/x.py", line 12, in func'
_FRAME_PY = re.compile(r'^\s*File "(?P<file>[^"]+)", line \d+, in (?P<func>\S+)')
# GCC/Clang/Rust-ish: '  #3 0x55 in some_func /path/file.c:42'
_FRAME_NATIVE = re.compile(r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+(?P<func>\S+)")

# Volatile details that must not enter a signature.
_HEX_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_LONG_NUM = re.compile(r"\b\d{3,}\b")
_PATHS = re.compile(r"(/[\w.\-]+)+")

# Messages that mean "the SUT correctly refused this input".
# Substring match, case-insensitive. Deliberately conservative: a false
# "rejection" hides a real bug, so anything ambiguous is left out and handled
# per-SUT via oracle.rejection_patterns instead.
_REJECTION_MARKERS = (
    "syntaxerror",
    "syntax error",
    "parseerror",
    "parseexception",
    "parsecancellation",
    "recognitionexception",
    "illegalargument",
    "lexer",
    "unexpected token",
    "unexpected character",
    "expecting",
    "mismatched input",
    "no viable alternative",
    "extraneous input",
    "compilationfailed",
    "evaluatorexception",
)


def norm_text(s: str | None) -> str:
    """Collapse newlines and runs of whitespace so two streams compare fairly."""
    if not s:
        return ""
    return " ".join(s.replace("\r\n", "\n").replace("\r", "\n").split())


def filter_banners(output: str | None, banners: tuple[str, ...] = ()) -> str:
    """Strip known start-up banners so they do not mask real output differences."""
    if not output:
        return ""
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in output.strip().splitlines():
        for phrase in banners:
            line = line.replace(phrase, "")
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def extract_exception_type(text: str | None) -> str:
    """Short exception type name, lowercased, or NO_EXCEPTION."""
    if not text:
        return NO_EXCEPTION
    m = _EXC_TYPE.search(text)
    return m.group(1).lower() if m else NO_EXCEPTION


def extract_exception_normalized(stderr_s: str | None, stdout_s: str | None = "") -> str:
    """One-line exception summary, in the same shape the research pipeline writes.

    Priority: 'Exception in thread ...' -> 'Caused by: ...' -> ANTLR diagnostic.
    """
    stderr_s = stderr_s or ""
    stdout_s = stdout_s or ""

    m = _JAVA_IN_THREAD.search(stderr_s)
    if m:
        etype = m.group(1).split(".")[-1]
        msg = (m.group(2) or "").strip()
        return f"{etype}: {msg}" if msg else etype

    m = _JAVA_CAUSED_BY.search(stderr_s)
    if m:
        etype = m.group(1).split(".")[-1]
        msg = (m.group(2) or "").strip()
        return f"{etype}: {msg}" if msg else etype

    m = _ANTLR_DIAG.search(stderr_s) or _ANTLR_DIAG.search(stdout_s)
    if m:
        return m.group(0).strip()

    # Generic fallback for non-JVM SUTs: the last 'SomeError: message' line.
    # Without this, every Python/JS/native failure collapses to <no_exception>
    # and distinct bugs share one signature.
    for line in reversed(stderr_s.strip().splitlines()):
        m = _GENERIC_EXC_LINE.match(line.strip())
        if m:
            etype, msg = m.group(1), (m.group(2) or "").strip()
            etype = etype.split(".")[-1]
            return f"{etype}: {msg}" if msg else etype

    return NO_EXCEPTION


def normalize_exception_for_compare(s: str | None) -> str:
    """Reduce an exception to a single comparable token (lowercased).

    Used by the differential oracle: two targets raising NullPointerException
    with different messages should still compare equal.
    """
    if not s:
        return NO_EXCEPTION
    s = s.strip()
    if s == NO_EXCEPTION:
        return NO_EXCEPTION
    t = extract_exception_type(s)
    if t != NO_EXCEPTION:
        return t
    return s.lower()


def matches_any(text: str | None, patterns: Sequence[str]) -> bool:
    """True if any regex matches, searched per line, case-insensitively."""
    if not text or not patterns:
        return False
    return any(re.search(p, text, re.IGNORECASE | re.MULTILINE) for p in patterns)


def looks_like_crash(stderr_s: str | None, stdout_s: str | None,
                     patterns: Sequence[str] | None) -> bool:
    """True when output carries a marker that means a genuine failure.

    Checked BEFORE rejection, so a broad rejection pattern can be written
    without it swallowing real bugs. For Rhino, `^js: ` covers every
    script-level diagnostic, while an engine defect surfaces as a Java stack
    trace into org.mozilla.javascript -- which this catches first.
    """
    return matches_any(f"{stderr_s or ''}\n{stdout_s or ''}", patterns or [])


def looks_like_rejection(
    stderr_s: str | None,
    stdout_s: str | None = "",
    patterns: Sequence[str] | None = None,
) -> bool:
    """True when the SUT reported a refusal rather than failing.

    `patterns` are regular expressions from `oracle.rejection_patterns`,
    matched (with re.search, per line, case-insensitively) against stderr and
    stdout. When supplied they REPLACE the built-in markers, because a SUT's own
    diagnostics are far more reliable than generic keywords.

    Example: Rhino exits 3 both for a script it refused to parse and for a Java
    crash, but prefixes every script-level diagnostic with "js: ". A pattern of
    `^js: ` separates the two exactly; keyword matching cannot.
    """
    text = f"{stderr_s or ''}\n{stdout_s or ''}"
    if patterns:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                return True
        return False
    return any(marker in text.lower() for marker in _REJECTION_MARKERS)


def top_frames(stderr_s: str | None, n: int = 5) -> list[str]:
    """First n stack frames, in whatever language the SUT reports them.

    Line numbers and addresses are deliberately dropped: they move whenever the
    SUT is recompiled, and a signature that changes on every build is useless.
    """
    if not stderr_s:
        return []
    frames: list[str] = []
    # Python prints "most recent call last": the frames that locate the failure come last.
    # Detected from the frame lines too: a long traceback's tail may have lost its header.
    innermost_last = ("Traceback (most recent call last)" in stderr_s
                      or bool(re.search(r'^\s*File ".*", line \d+', stderr_s, re.M)))
    for line in stderr_s.splitlines():
        m = _FRAME_JAVA.match(line)
        if m:
            frames.append(m.group(1))
            continue
        m = _FRAME_PY.match(line)
        if m:
            stem = m.group("file").rsplit("/", 1)[-1]
            frames.append(f"{stem}:{m.group('func')}")
            continue
        m = _FRAME_NATIVE.match(line)
        if m:
            frames.append(m.group("func"))
        if len(frames) >= n and not innermost_last:
            break
    return frames[-n:] if innermost_last else frames[:n]


def failure_signature(stderr_s: str | None, stdout_s: str | None = "", frames: int = 5) -> str:
    """A stable bucket key: exception type + top N frames, volatile detail removed."""
    etype = normalize_exception_for_compare(extract_exception_normalized(stderr_s, stdout_s))
    stack = top_frames(stderr_s, frames)
    raw = etype + "|" + "|".join(stack)
    raw = _HEX_ADDR.sub("0xADDR", raw)
    raw = _PATHS.sub("PATH", raw)
    raw = _LONG_NUM.sub("N", raw)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
