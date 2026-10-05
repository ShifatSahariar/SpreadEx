"""Run one input against one target, under a timeout and resource limits.

Everything here is a measurement. No judgement -- see oracle.py.
"""

from __future__ import annotations

import os
import resource
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .observation import Observation, preview, sha256_text

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MEM_MB = 2048
MAX_CAPTURE_BYTES = 1 << 20  # 1 MiB per stream


@dataclass
class Limits:
    timeout_s: float = DEFAULT_TIMEOUT_S
    memory_mb: int | None = DEFAULT_MEM_MB
    cpu_s: int | None = None
    max_open_files: int | None = 256

    def preexec(self):
        """Return a preexec_fn applying rlimits in the child, or None."""
        mem = self.memory_mb
        cpu = self.cpu_s or int(self.timeout_s * 2) + 1
        nofile = self.max_open_files

        def _apply():
            os.setsid()  # own process group, so we can kill the whole tree
            if mem:
                nbytes = mem * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
                except (ValueError, OSError):
                    pass  # macOS often refuses RLIMIT_AS; timeout still applies
            if cpu:
                try:
                    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
                except (ValueError, OSError):
                    pass
            if nofile:
                try:
                    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
                except (ValueError, OSError):
                    pass

        return _apply


@dataclass
class Target:
    """One system under test: a command template plus how to identify it."""

    name: str
    command: list[str]
    version: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    limits: Limits = field(default_factory=Limits)
    base_dir: Path | None = None   # project root; relative paths resolve here
    #: "file"  -- the input is a path, substituted for {input} or appended.
    #: "stdin" -- the input's BYTES are piped in and no path is passed. Plenty
    #: of real interpreters read only stdin; without this they cannot be
    #: tested at all, and appending a path they ignore makes every input look
    #: like a hang while they wait for input that never comes.
    input_mode: str = "file"

    def resolved_command(self) -> list[str]:
        """Resolve relative paths in the command against the project root.

        Users write `./parser.py` meaning "relative to my project", exactly as
        they would in a shell. The child process runs in a scratch directory so
        a misbehaving SUT cannot litter the project, which means a relative path
        would otherwise resolve against the wrong directory and every single
        input would look like a crash.
        """
        if self.base_dir is None:
            return list(self.command)
        out = []
        for part in self.command:
            if part.startswith(("./", "../")) or (part.startswith("/") is False and "/" in part):
                candidate = (self.base_dir / part).resolve()
                if candidate.exists():
                    out.append(str(candidate))
                    continue
            out.append(part)
        return out

    def resolved_cwd(self) -> str | None:
        """The directory the child runs in, or None for a clean scratch directory.

        A relative path is relative to the PROJECT, as every other path in
        spreadex.yaml is. It used to be handed to subprocess as written, so the
        same config ran in a different place depending on which directory
        `spreadex` was launched from -- and a UI server can be launched from
        anywhere.
        """
        if not self.cwd:
            return None
        path = Path(self.cwd).expanduser()
        if not path.is_absolute() and self.base_dir is not None:
            path = self.base_dir / path
        return str(path)

    def render(self, input_path: Path) -> list[str]:
        """Substitute {input} in the command template.

        If no argument mentions {input}, the path is appended -- the common case
        for `./parser file.js`. Under `input_mode: stdin` nothing is appended,
        because the program is not being given a file; an explicit {input} is
        still honoured, for a command that wants both.
        """
        command = self.resolved_command()
        if not any("{input}" in part for part in command):
            return list(command) if self.input_mode == "stdin" else [*command, str(input_path)]
        return [part.replace("{input}", str(input_path)) for part in command]

    @classmethod
    def from_config(cls, cfg: dict, defaults: dict | None = None,
                    base_dir: Path | None = None) -> "Target":
        defaults = defaults or {}
        timeout = _parse_duration(cfg.get("timeout", defaults.get("timeout", DEFAULT_TIMEOUT_S)))
        return cls(
            name=cfg.get("name", "sut"),
            command=list(cfg["command"]),
            input_mode=(cfg.get("input_mode") or defaults.get("input_mode") or "file"),
            version=cfg.get("version"),
            # `env: {LEVEL: 3}` is what a person types, and subprocess wants strings.
            env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
            cwd=cfg.get("cwd"),
            base_dir=base_dir,
            limits=Limits(
                timeout_s=timeout,
                memory_mb=cfg.get("memory_mb", defaults.get("memory_mb", DEFAULT_MEM_MB)),
            ),
        )


def _parse_duration(value) -> float:
    """Accept 5, 5.0, '5', '5s', '2m', '1h'."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600}
    if s and s[-1] in mult:
        return float(s[:-1]) * mult[s[-1]]
    return float(s)


def _decode(raw: bytes | None) -> str:
    if not raw:
        return ""
    return raw[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")


def run_one(target: Target, input_path: Path, input_hash: str | None = None) -> Observation:
    """Execute `target` on `input_path` and record what happened."""
    input_path = Path(input_path)
    if input_hash is None:
        input_hash = sha256_text(input_path.read_text(encoding="utf-8", errors="replace"))

    cmd = target.render(input_path)
    env = {**os.environ, **target.env}
    limits = target.limits

    # Under stdin mode the program is handed the bytes and then EOF. The EOF
    # matters as much as the bytes: a REPL given input but no end-of-stream
    # waits for more and is killed by the timeout, so every input would be
    # reported as a hang.
    # In file mode stdin is closed rather than inherited. A SUT that reads
    # stdin despite being handed a path would otherwise block on the terminal
    # the campaign was launched from, and be recorded as a timeout.
    stdin_bytes = input_path.read_bytes() if target.input_mode == "stdin" else b""

    timed_out = False
    exit_code: int | None = None
    signal_num: int | None = None
    out = err = ""

    with tempfile.TemporaryDirectory(prefix="spreadex-run-") as tmp:
        cwd = target.resolved_cwd() or tmp
        # subprocess raises the SAME FileNotFoundError for a missing command and
        # a missing working directory, which used to be reported as "command not
        # found" for a perfectly good command. Check the one we can name.
        if target.cwd and not Path(cwd).is_dir():
            raise RuntimeError(
                f"Target {target.name!r}: working directory not found: {cwd}\n"
                f"  Fix: correct `cwd` in spreadex.yaml, or remove it to run in a clean "
                f"scratch directory."
            )
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_bytes,
                capture_output=True,
                timeout=limits.timeout_s,
                cwd=cwd,
                env=env,
                preexec_fn=limits.preexec(),
                check=False,
            )
            out, err = _decode(proc.stdout), _decode(proc.stderr)
            rc = proc.returncode
            if rc is not None and rc < 0:
                signal_num = -rc          # POSIX: killed by signal -rc
                exit_code = rc
            else:
                exit_code = rc
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            out, err = _decode(exc.stdout), _decode(exc.stderr)
        except FileNotFoundError as exc:
            # A missing interpreter is a configuration error, not a SUT bug.
            raise RuntimeError(
                f"Target {target.name!r}: command not found: {cmd[0]!r}\n"
                f"  (resolved from {target.command[0]!r}"
                + (f" relative to {target.base_dir}" if target.base_dir else "")
                + ")\n  Fix: run `spreadex doctor`."
            ) from exc
        duration_ms = (time.perf_counter() - start) * 1000

    return Observation(
        input_hash=input_hash,
        sut_id=target.name,
        sut_version=target.version,
        exit_code=exit_code,
        signal=signal_num,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_hash=sha256_text(out),
        stderr_hash=sha256_text(err),
        stdout_preview=preview(out),
        stderr_preview=preview(err),
    )
