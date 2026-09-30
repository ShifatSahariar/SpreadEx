"""Where generated inputs come from.

Two kinds of source, behind one interface:

  corpus      an existing directory of inputs -- the "I have no grammar but I do
              have examples" case
  generators  grammar-based generators, each driven in its own environment

A source yields bytes plus the generator that produced them and what it cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..generators import GeneratorError, GeneratorManager
from ..generators.adapters import generate as run_generator

MAX_INPUT_BYTES = 1 << 20


@dataclass
class GeneratedInput:
    data: bytes
    generator: str
    cost_ms: float


def grammar_for(config, generator_id: str, derived: dict[str, Path] | None = None) -> Path | None:
    """Resolve this generator's grammar.

    An explicit per-generator entry always wins:

        grammar:
          fuzzingbook: grammars/rhino.py
          fandango:    grammars/rhino.fan

    Otherwise a single `source:` is adapted into each generator's dialect:

        grammar:
          source: grammars/rhino.bnf
    """
    g = config.grammar or {}
    explicit = g.get(generator_id)
    if explicit:
        return (config.project_root / explicit).resolve()
    if derived and generator_id in derived:
        return derived[generator_id]
    source = g.get("source")
    if not source:
        return None
    return (config.project_root / source).resolve()


def derive_grammars(config, generators: list[str], log=print) -> dict[str, Path]:
    """Adapt `grammar.source` into each generator's dialect, cached by content.

    Generators that already have an explicit grammar are left alone, and one
    that cannot express the source is skipped with its reason rather than being
    handed a grammar it will choke on.
    """
    import hashlib

    from ..grammar import GrammarError, RenderError, adapt

    g = config.grammar or {}
    source = g.get("source")
    needed = [gid for gid in generators if not g.get(gid)]
    if not source or not needed:
        return {}

    source_path = (config.project_root / source).resolve()
    if not source_path.exists():
        raise RuntimeError(
            f"Grammar source not found: {source_path}\n"
            f"  Fix: correct `grammar.source` in spreadex.yaml."
        )

    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
    out_dir = config.state_dir / "cache" / "grammars" / digest
    try:
        result = adapt(source_path, needed, out_dir, start=g.get("start"))
    except (GrammarError, RenderError) as exc:
        raise RuntimeError(f"Could not adapt {source_path.name}:\n  {exc}") from exc

    if result.report.errors:
        detail = "\n".join(f.render() for f in result.report.errors)
        raise RuntimeError(
            f"{source_path.name} has grammar errors, so no dialects were derived:\n{detail}\n"
            f"  Check it with: spreadex grammar check {source}"
        )

    if result.written:
        log(f"  grammar: derived {len(result.written)} dialect(s) from {source_path.name}")
    for gid, risks in result.risks.items():
        for risk in risks:
            log(f"  ! {gid}: {risk}")
    for gid, why in result.skipped.items():
        log(f"  ! {gid}: {why}")
    return result.written


def collect(config, budget_s: float, log=print, manager: GeneratorManager | None = None):
    """Gather inputs from every configured source, within the generation budget."""
    out: list[GeneratedInput] = []

    corpus_cfg = config.raw.get("corpus") or {}
    if corpus_cfg.get("path"):
        out.extend(from_corpus(config.project_root / corpus_cfg["path"], log=log))

    generators = list(config.generators or [])
    if not generators and not out:
        raise RuntimeError(
            "No input source configured.\n"
            "  Fix: add `corpus: {path: ./seeds}` for an existing corpus, or\n"
            "       `generators: [fuzzingbook]` with a `grammar:` entry."
        )

    if generators:
        mgr = manager or GeneratorManager()
        # Never install implicitly: report and stop, naming the fix.
        mgr.ensure(generators, log=log, auto_install=False)

        derived = derive_grammars(config, generators, log=log)
        count = int((config.raw.get("generation") or {}).get("count", 200))
        # Uniform allocation. The honest default, and the baseline any adaptive
        # policy has to beat.
        per_generator = budget_s / len(generators)
        for gid in generators:
            grammar = grammar_for(config, gid, derived)
            if grammar is None:
                log(f"  ! {gid}: no grammar configured -- skipping")
                continue
            try:
                batch = run_generator(gid, grammar, count, seed=config.seed,
                                      timeout=per_generator, manager=mgr)
            except GeneratorError as exc:
                # One broken generator must not abort a campaign that has others.
                log(f"  ! {gid}: {exc}")
                continue
            log(f"  {gid}: {len(batch.inputs)} inputs in {batch.elapsed_ms / 1000:.1f}s")
            out.extend(
                GeneratedInput(data, gid, batch.cost_per_input_ms) for data in batch.inputs
            )

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
