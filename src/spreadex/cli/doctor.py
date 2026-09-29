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
    if corpus:
        p = config.project_root / corpus
        n = sum(1 for x in p.rglob("*") if x.is_file()) if p.exists() else 0
        checks.append(Check("corpus", OK if n else FAIL, f"{n} files in {corpus}",
                            f"put seed inputs in {corpus}/"))
    if not corpus and not config.generators:
        checks.append(Check("input source", FAIL, "neither a corpus nor any generators",
                            "add `corpus: {path: ./seeds}` or `generators: [fuzzingbook]`"))

    # Generators: ask the manager which are actually usable, and check that
    # each one has a grammar in the dialect it speaks.
    if config.generators:
        from ..core.sources import grammar_for
        from ..generators import GeneratorError, GeneratorManager
        from ..generators.adapters import ADAPTERS

        mgr = GeneratorManager()
        for gid in config.generators:
            try:
                gen = mgr.get(gid)
            except GeneratorError:
                checks.append(Check(f"generator '{gid}'", FAIL, "not in the catalog",
                                    "spreadex generators list"))
                continue

            st = mgr.status(gid)
            if not st.installed:
                checks.append(Check(f"generator '{gen.name}'", FAIL, "not installed",
                                    f"spreadex generators install {gid}"))
            elif gid not in ADAPTERS or _adapter_is_stub(gid):
                checks.append(Check(f"generator '{gen.name}'", WARN,
                                    "installed, but generation is not wired up in v0.1",
                                    "use fuzzingbook, fandango or isla"))
            else:
                checks.append(Check(f"generator '{gen.name}'", OK,
                                    f"{st.version or 'installed'} ({st.where})"))

            grammar = grammar_for(config, gid)
            if grammar is None:
                checks.append(Check(f"  grammar for '{gid}'", FAIL, "none configured",
                                    f"add `grammar: {{{gid}: <path>}}` "
                                    f"(dialect: {gen.grammar_dialect})"))
            elif not grammar.exists():
                checks.append(Check(f"  grammar for '{gid}'", FAIL, f"missing: {grammar}",
                                    "correct the path under `grammar:`"))
            else:
                checks.append(Check(f"  grammar for '{gid}'", OK,
                                    f"{grammar.name} ({gen.grammar_dialect})"))

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


def _adapter_is_stub(generator_id: str) -> bool:
    """True when the catalog knows a generator but generation is not implemented."""
    return generator_id in {"grammarinator"}


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
