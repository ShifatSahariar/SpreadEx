"""`spreadex doctor` -- emit FIXES, not diagnoses.

Every failing check must tell the user the exact command that repairs it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""

    def render(self) -> str:
        line = f"  {MARK[self.status]} {self.name}"
        if self.detail:
            line += f"  {self.detail}"
        if self.fix and self.status != OK:
            line += f"\n      fix: {self.fix}"
        return line


def run_checks(config=None, project_root: Path | None = None) -> list[Check]:
    checks: list[Check] = []

    if config is None:
        checks.append(Check("spreadex.yaml", FAIL, "not found",
                            "run `spreadex init` in your project root"))
        return checks
    checks.append(Check("spreadex.yaml", OK, str(config.project_root / "spreadex.yaml")))

    # Targets: the single most common source of a broken first run.
    for t in config.targets:
        exe = t.command[0]
        found = shutil.which(exe) or (Path(exe).exists() and str(Path(exe).resolve()))
        if found:
            checks.append(Check(f"target '{t.name}'", OK, f"{exe} -> {found}"))
        else:
            checks.append(Check(
                f"target '{t.name}'", FAIL, f"{exe} not found on PATH",
                f"install it, or give an absolute path in sut.targets[].command",
            ))
        if not any("{input}" in p for p in t.command):
            checks.append(Check(
                f"target '{t.name}' input", WARN,
                "no {input} placeholder; the path will be appended as the last argument",
                "add \"{input}\" to the command if the file goes elsewhere",
            ))

    if config.is_differential:
        checks.append(Check("oracle", OK, f"differential over {len(config.targets)} targets"))
    else:
        checks.append(Check("oracle", OK, f"{config.oracle.get('type', 'crash')} (single target)"))

    # Input sources.
    corpus = (config.raw.get("corpus") or {}).get("path")
    grammar = config.grammar.get("source")
    if corpus:
        p = config.project_root / corpus
        n = sum(1 for x in p.rglob("*") if x.is_file()) if p.exists() else 0
        checks.append(Check("corpus", OK if n else FAIL, f"{n} files in {corpus}",
                            f"put seed inputs in {corpus}/"))
    if grammar:
        p = config.project_root / grammar
        checks.append(Check("grammar", OK if p.exists() else FAIL, str(grammar),
                            f"create {grammar}, or correct grammar.source"))
    if not corpus and not grammar:
        checks.append(Check("input source", FAIL, "neither corpus nor grammar configured",
                            "add `corpus: {path: ./seeds}` or `grammar: {source: grammar.g4}`"))

    # Generators.
    for g in config.generators:
        if g == "fuzzingbook":
            try:
                import fuzzingbook  # noqa: F401
                checks.append(Check("generator 'fuzzingbook'", OK))
            except ImportError:
                checks.append(Check("generator 'fuzzingbook'", FAIL, "not installed",
                                    "pip install fuzzingbook"))
        else:
            checks.append(Check(f"generator '{g}'", WARN, "not wired up in v0.1",
                                "use `generators: [fuzzingbook]` or a corpus for now"))

    # Embedding backend.
    model = config.embedding.get("model", "tfidf")
    if model == "tfidf":
        try:
            import sklearn  # noqa: F401
            checks.append(Check("embedding 'tfidf'", OK, "no GPU or API key needed"))
        except ImportError:
            checks.append(Check("embedding 'tfidf'", FAIL, "scikit-learn missing",
                                "pip install scikit-learn"))
    else:
        try:
            import torch  # noqa: F401
            checks.append(Check(f"embedding '{model}'", OK))
        except ImportError:
            checks.append(Check(f"embedding '{model}'", FAIL, "torch missing",
                                "pip install 'spreadex[neural]', or set embedding.model: tfidf"))

    # Java, only when a target actually needs it.
    if any(t.command[0] in ("java", "javac") for t in config.targets):
        checks.append(_java_check())

    # Writable state dir.
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        probe = config.state_dir / ".write-probe"
        probe.write_text("x")
        probe.unlink()
        checks.append(Check("corpus writable", OK, str(config.state_dir)))
    except OSError as exc:
        checks.append(Check("corpus writable", FAIL, str(exc),
                            f"check permissions on {config.state_dir}"))
    return checks


def _java_check() -> Check:
    exe = shutil.which("java")
    if not exe:
        return Check("java", FAIL, "not on PATH",
                     "install a JDK (e.g. `brew install openjdk`) or set JAVA_HOME")
    try:
        p = subprocess.run(["java", "-version"], capture_output=True, timeout=10, check=False)
        ver = ((p.stderr or b"") + (p.stdout or b"")).decode(errors="replace").splitlines()
        return Check("java", OK, ver[0].strip() if ver else exe)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("java", WARN, f"found but not runnable: {exc}", "check your JDK installation")


def summarize(checks: list[Check]) -> tuple[int, int, int]:
    return (
        sum(c.status == OK for c in checks),
        sum(c.status == WARN for c in checks),
        sum(c.status == FAIL for c in checks),
    )
