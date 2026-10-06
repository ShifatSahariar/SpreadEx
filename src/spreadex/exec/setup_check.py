"""Recognise a system under test that could not even start.

A wrong path or a missing interpreter module makes the SUT exit non-zero on every input, and
an oracle then reports every input as a crash: one campaign of noise. These messages come from
the shell, the interpreter or the JVM -- not from the system under test -- so they can be
recognised before a campaign starts, by `spreadex doctor` and by the Workbench's Test connection.
"""

from __future__ import annotations

import re

from .observation import Observation

# Each pattern is the launcher's own wording, so it does not match a system that merely
# rejects its input.
_PATTERNS = [
    (re.compile(r"can't open file .*No such file or directory", re.I), "the script it runs was not found"),
    (re.compile(r"^.*: (No such file or directory|command not found)$", re.M), "a file or program in the command was not found"),
    (re.compile(r"Error: Could not find or load main class", re.I), "Java could not find the main class"),
    (re.compile(r"Error: Unable to access jarfile", re.I), "Java could not find the jar file"),
    (re.compile(r"^ModuleNotFoundError: No module named", re.M), "a Python module the system needs is not installed"),
    (re.compile(r"^Error: Cannot find module", re.M), "a Node.js module the system needs was not found"),
]


def setup_failure(obs: Observation) -> str | None:
    """A short reason when the run failed to start the system at all; None otherwise."""
    if obs.exit_code in (126, 127):
        return ("the shell could not run the command (exit 126: not executable)" if obs.exit_code == 126
                else "the shell could not find the command (exit 127)")
    text = "\n".join(t for t in (getattr(obs, "stderr_tail", None) or obs.stderr_preview, obs.stdout_preview) if t)
    for pattern, reason in _PATTERNS:
        m = pattern.search(text)
        if m:
            line = m.group(0).strip().splitlines()[-1][:200]
            return f"{reason}: {line}"
    return None
