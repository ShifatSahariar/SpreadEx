"""Recognise a system under test that could not even start.

A wrong path or a missing interpreter module makes the SUT exit non-zero on every input, and
an oracle then reports every input as a crash: one campaign of noise. These messages come from
the shell, the interpreter or the JVM -- not from the system under test -- so they can be
recognised before a campaign starts, by `spreadex doctor` and by the Workbench's Test connection.
"""

from __future__ import annotations

import re
from pathlib import Path

from .observation import Observation

# Each pattern is the launcher's own wording, so it does not match a system that merely
# rejects its input.
_PATTERNS = [
    (re.compile(r"can't open file .*No such file or directory", re.I), "the script it runs was not found"),
    (re.compile(r"^.*: (No such file or directory|command not found)$", re.M), "a file or program in the command was not found"),
    (re.compile(r"Error: Could not find or load main class", re.I), "Java could not find the main class"),
    # The JVM reserves more address space than SpreadEx's per-input memory limit allows (Linux
    # enforces it; macOS does not). Every input would otherwise look like a crash.
    (re.compile(r"Error occurred during initialization of VM", re.I),
     "Java could not start under the memory limit; raise sut.memory_mb or add JVM flags such as "
     "-Xmx256m -XX:CompressedClassSpaceSize=64m"),
    (re.compile(r"Error: Unable to access jarfile", re.I), "Java could not find the jar file"),
    (re.compile(r"^ModuleNotFoundError: No module named", re.M), "a Python module the system needs is not installed"),
    (re.compile(r"^Error: Cannot find module", re.M), "a Node.js module the system needs was not found"),
]


def missing_files(target) -> list[str]:
    """Arguments that name a file the project does not have.

    The system runs in a scratch folder, and only files that exist are rewritten to their
    project path, so a missing one would be reported by the interpreter against that scratch
    folder -- a path the user has never seen. Naming it against the project folder instead
    points at the place to look.
    """
    base = getattr(target, "base_dir", None)
    if base is None:
        return []
    roots = [Path(base)]
    cwd = target.resolved_cwd() if target.cwd else None
    if cwd:
        roots.append(Path(cwd))
    out = []
    for part in target.command[1:]:
        if (not part or part.startswith("-") or "{input}" in part or "=" in part
                or Path(part).is_absolute()):
            continue
        if "/" not in part and not Path(part).suffix:          # a word, not a file name
            continue
        if not any((r / part).exists() for r in roots):
            out.append(part)
    return out


def setup_failure(obs: Observation, target=None) -> str | None:
    """A short reason when the run failed to start the system at all; None otherwise.

    With the target, a file named in the command that is missing from the project is
    reported against the project folder rather than the scratch folder the system ran in.
    """
    if obs.exit_code in (126, 127):
        return ("the shell could not run the command (exit 126: not executable)" if obs.exit_code == 126
                else "the shell could not find the command (exit 127)")
    text = "\n".join(t for t in (getattr(obs, "stderr_tail", None) or obs.stderr_preview, obs.stdout_preview) if t)
    for pattern, reason in _PATTERNS:
        m = pattern.search(text)
        if m:
            missing = missing_files(target) if target is not None else []
            if missing:
                names = ", ".join(missing)
                return (f"{reason}: {names} is not in the project folder ({target.base_dir})"
                        if len(missing) == 1 else
                        f"{reason}: {names} are not in the project folder ({target.base_dir})")
            line = m.group(0).strip().splitlines()[-1][:200]
            return f"{reason}: {line}"
    return None
