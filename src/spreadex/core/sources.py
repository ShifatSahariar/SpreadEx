"""Where generated inputs come from.

v0.1 supports two sources, both of which work today with no new integrations:

  corpus:     an existing directory of inputs (the "I have no grammar but I do
              have examples" case -- the small-company persona)
  fuzzingbook: the one generator adapter in this repo that is fully implemented

Fandango, Grammarinator and ISLa land next, behind the same interface: a source
is anything that yields (bytes, generator_name, cost_ms).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAX_INPUT_BYTES = 1 << 20


@dataclass
class GeneratedInput:
    data: bytes
    generator: str
    cost_ms: float


def collect(config, budget_s: float, log=print) -> list[GeneratedInput]:
    """Gather inputs from every configured source, within the generation budget."""
    out: list[GeneratedInput] = []
    sources = list(config.generators or [])
    corpus_cfg = (config.raw.get("corpus") or {})
    if corpus_cfg.get("path"):
        out.extend(from_corpus(config.project_root / corpus_cfg["path"], log=log))

    if not sources and not out:
        raise RuntimeError(
            "No input source configured.\n"
            "  Fix: add `corpus: {path: ./seeds}` for an existing corpus, or\n"
            "       `generators: [fuzzingbook]` with `grammar.source` set."
        )

    per_source = budget_s / max(1, len(sources)) if sources else 0.0
    for name in sources:
        if name == "fuzzingbook":
            out.extend(from_fuzzingbook(config, per_source, log=log))
        else:
            log(f"  ! generator {name!r} is not wired up yet in v0.1 -- skipping")
    return out


def from_corpus(path: Path, log=print) -> list[GeneratedInput]:
    path = Path(path)
    if not path.exists():
        raise RuntimeError(
            f"Corpus directory not found: {path}\n"
            f"  Fix: create it, or correct `corpus.path` in spreadex.yaml."
        )
    items: list[GeneratedInput] = []
    for f in sorted(p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")):
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if 0 < len(data) <= MAX_INPUT_BYTES:
            items.append(GeneratedInput(data, "corpus", 0.0))
    log(f"  corpus: {len(items)} inputs from {path}")
    return items


def from_fuzzingbook(config, budget_s: float, log=print) -> list[GeneratedInput]:
    """Drive the existing fuzzingbook adapter, then read back what it wrote."""
    grammar = config.grammar.get("source")
    if not grammar:
        log("  ! fuzzingbook needs `grammar.source` in spreadex.yaml -- skipping")
        return []
    grammar_path = config.project_root / grammar
    if not grammar_path.exists():
        raise RuntimeError(
            f"Grammar not found: {grammar_path}\n  Fix: correct `grammar.source` in spreadex.yaml."
        )

    import tempfile

    n = int(config.raw.get("generation", {}).get("count", 500))
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="spreadex-gen-") as tmp:
        outdir = Path(tmp)
        try:
            from webapp.tool_mode.generators.fuzzingbook import generate
        except ImportError as exc:
            raise RuntimeError(
                "The fuzzingbook adapter is unavailable.\n"
                "  Fix: pip install fuzzingbook, and run from the repository root."
            ) from exc
        generate("fuzz_equal", grammar_path, n, outdir)
        files = sorted(p for p in outdir.rglob("*") if p.is_file())
        elapsed_ms = (time.perf_counter() - started) * 1000
        per = elapsed_ms / max(1, len(files))
        items = [GeneratedInput(p.read_bytes(), "fuzzingbook", per) for p in files]
    log(f"  fuzzingbook: {len(items)} inputs in {elapsed_ms/1000:.1f}s")
    return items
