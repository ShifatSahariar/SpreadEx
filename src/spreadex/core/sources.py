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

from ..exec.runner import _parse_duration
from ..generators import GeneratorError, GeneratorManager
from ..generators.adapters import generate as run_generator

MAX_INPUT_BYTES = 1 << 20


@dataclass
class GeneratedInput:
    data: bytes
    generator: str
    cost_ms: float


@dataclass
class GenerationStats:
    """What one generator was asked for, and what it actually cost.

    Recorded per generator because the headline question -- which generator
    deserves the next budget -- is not answerable without it. Asking four
    generators for 150 inputs each and comparing the result compares them at
    wildly different computational effort: on examples/rhino that was 2.5s for
    Fandango against 44.8s for ISLa, an 18x difference hidden behind an
    identical input count.
    """

    generator: str
    mode: str                 # "count" or "time"
    requested_count: int | None = None
    requested_seconds: float | None = None
    elapsed_s: float = 0.0
    produced: int = 0
    partial: bool = False     # the budget stopped it before it was finished
    cap: int | None = None    # the ceiling it was allowed to reach
    hit_cap: bool = False     # ...and whether it reached it, which in time
                              # mode means the comparison was not really
                              # equal-time for this generator

    @property
    def throughput_per_s(self) -> float:
        return self.produced / self.elapsed_s if self.elapsed_s > 0 else 0.0

    def as_dict(self) -> dict:
        return {
            "generator": self.generator,
            "mode": self.mode,
            "requested_count": self.requested_count,
            "requested_seconds": (round(self.requested_seconds, 3)
                                  if self.requested_seconds is not None else None),
            "elapsed_s": round(self.elapsed_s, 3),
            "produced": self.produced,
            "throughput_per_s": round(self.throughput_per_s, 3),
            "partial": self.partial,
            "cap": self.cap,
            "hit_cap": self.hit_cap,
        }


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


def _apply_native_constraints(native: dict, written: dict, log) -> None:
    """Hand a generator the constraint file the user wrote for IT, exactly as written.

    No translation: a Fandango file goes to Fandango and an ISLa file to ISLa. Anything
    else the user described stays guidance and is not silently turned into either.
    """
    import shutil

    fan = native.get("fandango")
    if fan and "fandango" in written:
        target = written["fandango"]
        target.write_text(target.read_text().rstrip() + f"\n\n# --- constraints from {fan.name} (used as written)\n"
                          + fan.read_text().strip() + "\n")
        log(f"  constraints: Fandango uses {fan.name} as written")
    isla = native.get("isla")
    if isla and "isla" in written:
        shutil.copyfile(isla, written["isla"].with_suffix(".isla"))
        log(f"  constraints: ISLa uses {isla.name} as written")


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

    # A generator the user switched constraints off for gets the grammar alone.
    native = {gid: (config.project_root / rel) for gid, rel in config.semantics.native.items()
              if (config.generator_options.get(gid) or {}).get("constraints", True)}
    h = hashlib.sha256(source_path.read_bytes())
    for gid in sorted(native):                      # editing a native spec must not hit a stale cache
        h.update(gid.encode() + native[gid].read_bytes())
    digest = h.hexdigest()[:12]
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

    _apply_native_constraints(native, result.written, log)

    if result.written:
        log(f"  grammar: derived {len(result.written)} dialect(s) from {source_path.name}")
    for gid, risks in result.risks.items():
        for risk in risks:
            log(f"  ! {gid}: {risk}")
    for gid, why in result.skipped.items():
        log(f"  ! {gid}: {why}")
    return result.written


#: Time mode asks for "as many as you can" and lets the clock stop it. A
#: ceiling is still needed, because a fast generator on a small grammar can
#: emit faster than the rest of the pipeline can absorb -- Grammarinator
#: produced 20,000 JavaScript programs in 11.7 seconds.
#:
#: 5,000 per generator, not more, because the diversity map is the real limit:
#: scripts/scale_audit.py measures Affinity Propagation at 2.5 GB for 5,000
#: pooled inputs and 6.3 GB for 10,000. Four generators at this cap can still
#: pool 20,000 and want ~25 GB, which is why signals/base.py checks the
#: machine's memory before clustering rather than after.
DEFAULT_TIME_MODE_CAP = 5000


def collect(config, budget_s: float, log=print, manager: GeneratorManager | None = None,
            stats: list | None = None):
    """Gather inputs from every configured source, within the generation budget.

    `stats`, if given, is filled with one GenerationStats per generator. The
    campaign passes a list so the manifest can record what each generator was
    asked for and what it actually spent.
    """
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
        gen_cfg = config.raw.get("generation") or {}
        mode = (gen_cfg.get("mode") or "count").lower()

        # Uniform allocation. The honest default, and the baseline any adaptive
        # policy has to beat.
        per_generator = budget_s / len(generators)
        if mode == "time":
            seconds = gen_cfg.get("per_generator")
            seconds = _parse_duration(seconds) if seconds is not None else per_generator
            cap = int(gen_cfg.get("cap", DEFAULT_TIME_MODE_CAP))
            log(f"  equal time: {seconds:.0f}s per generator")
        else:
            seconds = per_generator
            cap = int(gen_cfg.get("count", 200))

        for gid in generators:
            grammar = grammar_for(config, gid, derived)
            if grammar is None:
                log(f"  ! {gid}: no grammar configured -- skipping")
                continue
            st = GenerationStats(
                generator=gid, mode=mode,
                requested_count=None if mode == "time" else cap,
                requested_seconds=seconds,
                cap=cap,
            )
            try:
                batch = run_generator(gid, grammar, cap, seed=config.seed,
                                      timeout=seconds, manager=mgr)
            except GeneratorError as exc:
                # One broken generator must not abort a campaign that has others.
                log(f"  ! {gid}: {exc}")
                if stats is not None:
                    stats.append(st)
                continue

            st.elapsed_s = batch.elapsed_ms / 1000
            st.produced = len(batch.inputs)
            st.partial = batch.partial
            st.hit_cap = st.produced >= cap
            if stats is not None:
                stats.append(st)

            if mode == "time":
                # In time mode being stopped by the clock is the design, not a
                # shortfall: every generator is meant to use its whole share.
                note = f" ({st.throughput_per_s:.1f}/s)"
                if st.hit_cap:
                    note += f" -- hit the {cap} cap after {st.elapsed_s:.1f}s of its {seconds:.0f}s"
            else:
                note = (f" (budget exhausted; asked for {cap})" if batch.partial else "")
            log(f"  {gid}: {len(batch.inputs)} inputs in "
                f"{batch.elapsed_ms / 1000:.1f}s{note}")
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
