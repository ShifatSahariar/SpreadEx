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


def grammar_for(config, generator_id: str) -> Path | None:
    """Resolve this generator's grammar.

    Generators speak different dialects, so `grammar:` may name one file per
    generator. A single `source:` is used for all of them, which is only correct
    when they share a dialect -- the grammar adapter that converts one grammar
    into many is a later phase, and until it exists the mapping is explicit.

        grammar:
          fuzzingbook: grammars/rhino_grammar.py
          fandango:    grammars/rhino.fan
          isla:        grammars/rhino.bnf
    """
    g = config.grammar or {}
    path = g.get(generator_id) or g.get("source")
    if not path:
        return None
    return (config.project_root / path).resolve()


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

        count = int((config.raw.get("generation") or {}).get("count", 200))
        # Uniform allocation. The honest default, and the baseline any adaptive
        # policy has to beat.
        per_generator = budget_s / len(generators)
        for gid in generators:
            grammar = grammar_for(config, gid)
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
