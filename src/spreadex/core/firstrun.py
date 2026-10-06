"""Spot "crashes" that are really the system rejecting its input.

A new project rarely has `oracle.rejection_patterns` yet, so a parser that reports invalid input
with a non-zero exit is reported as crashing on every invalid input. A real crash leaves a trace
-- a traceback, an exception, a signal, a sanitizer report -- while a rejection is usually one
short diagnostic line. Signatures that look like the latter are reported with a pattern to paste
into spreadex.yaml. It is a hint, never applied automatically: only the user knows their system.
"""

from __future__ import annotations

import re

# What a crash, as opposed to a diagnostic, leaves behind.
_CRASH_MARKERS = re.compile(
    r"Traceback \(most recent call last\)|Exception|panicked at|Segmentation fault|core dumped|"
    r"AddressSanitizer|Assertion|Fatal|^\s+at [\w$.]+\(|stack overflow|Aborted",
    re.I | re.M)


def suggest_pattern(line: str) -> str:
    """The same rule the Workbench's strategy step uses: the stable prefix of the message.

    A short word before the first colon -- `invalid:`, `calc:`, `error:` -- is usually the
    system's own rejection prefix, and matches every rejection rather than this one message.
    """
    colon = line.find(":")
    if 3 <= colon <= 30:
        prefix = line[:colon]
    else:
        cut = re.search(r"[\"'\d]", line)
        prefix = line[: cut.start()] if cut else line
        if not cut and ":" in prefix:
            prefix = prefix[: prefix.index(":")]
        if len(prefix.strip()) < 3:
            prefix = line[:40]
    return "^" + re.escape(prefix).replace("\\ ", " ")


def rejection_hints(store, run_id: str) -> list[dict]:
    """Crash signatures in this run whose output reads like a rejection, with a pattern each."""
    rows = store.conn.execute(
        """SELECT e.signature, COUNT(DISTINCT e.blob_hash) n, MIN(e.exit_code) lo, MAX(e.exit_code) hi,
                  MAX(e.signal) sig, f.example_stderr err
           FROM executions e LEFT JOIN failures f ON f.signature = e.signature
           WHERE e.run_id=? AND e.verdict='crash' AND e.signature IS NOT NULL
           GROUP BY e.signature""", (run_id,)).fetchall()
    hints = []
    for r in rows:
        err = (r["err"] or "").strip()
        lines = [l.strip() for l in err.splitlines() if l.strip()]
        if r["sig"] is not None or r["lo"] != r["hi"] or r["lo"] in (None, 0) or not lines:
            continue
        if len(lines) > 3 or _CRASH_MARKERS.search(err):
            continue
        hints.append({"signature": r["signature"], "inputs": r["n"], "exit_code": r["lo"],
                      "line": lines[0][:200], "pattern": suggest_pattern(lines[0])})
    return hints
