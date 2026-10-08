"""The Campaign Manager owns the workflow and the budget.

    Generate -> Validate -> Signals -> Prioritize -> Execute -> Observe
             -> Oracle -> Persist

Everything else (CLI, browser UI, CI) calls into this. Putting the loop here
rather than inside a pipeline script is what makes adaptive allocation,
regression mode, multiple SUT configurations and resumable campaigns additions
rather than rewrites.
"""

from __future__ import annotations

import json

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import __version__
from ..corpus import CorpusStore
from ..exec import run_one
from ..exec.oracle import Judgement, Verdict, make_oracle
from ..signals import Item, make_signal
from . import sources
from .budget import Clock, uniform_allocation
from ..exec.inputs import InputFiles
from .config import Config
from .lock import RunLock, cancel_file
from .selection import Selection, apply as apply_selection, choose as choose_generators
from .manifest import Manifest, capture_environment, probe_target_version

Logger = Callable[[str], None]


@dataclass
class CampaignResult:
    run_id: str
    run_dir: Path
    generated: int = 0
    valid: int = 0
    prioritized: int = 0
    executed: int = 0
    verdicts: dict[str, int] = field(default_factory=dict)
    signatures: list[tuple[str, str, int]] = field(default_factory=list)
    new_signatures: list[str] = field(default_factory=list)
    generator_scores: dict[str, float] = field(default_factory=dict)
    generator_counts: dict[str, int] = field(default_factory=dict)
    generator_cost_ms: dict[str, float] = field(default_factory=dict)
    k_eff: int | None = None
    budget_curve: list[tuple[int, int]] = field(default_factory=list)  # (executed, distinct signatures)
    exec_budget_s: float = 0.0
    exec_elapsed_s: float = 0.0
    #: Anything the selection signal wants the reader to know before trusting
    #: the CC numbers. Carried into the manifest so a replay sees it too.
    signal_caveats: list[str] = field(default_factory=list)
    #: Per generator: what it was asked for, what it spent, what it produced.
    #: Without this a CC comparison cannot be read as fair or unfair.
    generation_stats: list[dict] = field(default_factory=list)
    #: Set when the campaign kept only the top generators by CC (see core/selection.py).
    selection: dict | None = None

    @property
    def failures(self) -> int:
        return sum(self.verdicts.get(v.value, 0) for v in (Verdict.CRASH, Verdict.TIMEOUT, Verdict.DIVERGENCE))


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


class Campaign:
    def __init__(self, config: Config, log: Logger = print,
                 stop_event: threading.Event | None = None, origin: str = "cli") -> None:
        self.config = config
        self.log = log
        self.store = CorpusStore(config.state_dir)
        #: Set from another thread (the UI) to stop after the current input.
        self.stop_event = stop_event or threading.Event()
        self.origin = origin
        self.run_id: str | None = None

    def cancelled(self) -> bool:
        """Asked to stop -- by the event, or by a `cancel` file another process wrote."""
        if self.stop_event.is_set():
            return True
        if self.run_id and cancel_file(self.config.state_dir, self.run_id).exists():
            self.stop_event.set()
            return True
        return False

    # ------------------------------------------------------------------ run

    def run(self, run_id: str | None = None, signal_override: str | None = None,
            jobs: int = 1) -> CampaignResult:
        lock = RunLock(self.config.state_dir)
        lock.acquire(origin=self.origin)
        try:
            with self.store as store:
                store.mark_abandoned()  # we hold the lock: anything 'running' is dead
                # Only a generated id is made unique; an id the caller chose and reused stays an error.
                run_id = run_id or store.unique_run_id(new_run_id())
            self.run_id = run_id
            lock.set_run(run_id)
            try:
                return self._run(run_id, signal_override, jobs)
            except BaseException as exc:
                with self.store as store:
                    store.finish_run(run_id, status="cancelled"
                                     if isinstance(exc, KeyboardInterrupt) else "failed")
                raise
        finally:
            lock.release()

    def _run(self, run_id: str, signal_override: str | None, jobs: int) -> CampaignResult:
        cfg = self.config
        signal_name = signal_override or cfg.signal

        with self.store as store:
            run_dir = store.start_run(
                run_id,
                config_hash=cfg.hash(),
                seed=cfg.seed,
                gen_budget_s=cfg.budget.generation_s,
                exec_budget_s=cfg.budget.execution_s,
                signal_name=signal_name,
                origin=self.origin,
            )
            result = CampaignResult(run_id=run_id, run_dir=run_dir,
                                    exec_budget_s=cfg.budget.execution_s)
            manifest = Manifest(
                run_id=run_id,
                spreadex_version=__version__,
                config_hash=cfg.hash(),
                config=cfg.raw,
                semantics=cfg.semantics_digest(),
                seed=cfg.seed,
                signal=signal_name,
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                effective={
                    "generation_s": cfg.budget.generation_s,
                    "execution_s": cfg.budget.execution_s,
                    "max_inputs": cfg.budget.max_inputs,
                    "signal": signal_name,
                },
                environment=capture_environment(),
                targets=[_target_provenance(t) for t in cfg.targets],
            )

            # 1. Generate -----------------------------------------------------
            self.log("Generating...")
            allocation = uniform_allocation(list(cfg.generators), cfg.budget.generation_s)
            gen_stats: list = []
            generated = sources.collect(cfg, cfg.budget.generation_s, log=self.log,
                                        stats=gen_stats)
            result.generation_stats = [st.as_dict() for st in gen_stats]
            result.generated = len(generated)
            if not generated:
                raise RuntimeError(
                    "No inputs were produced.\n"
                    "  Fix: check `corpus.path` / `grammar.source` in spreadex.yaml, "
                    "then re-run `spreadex doctor`."
                )

            # 2. Store + validate --------------------------------------------
            items: list[Item] = []
            origins: dict[str, set[str]] = {}   # blob -> every source that produced it
            produced: list[tuple[str, str]] = []
            for gi in generated:
                text = gi.data.decode("utf-8", errors="replace")
                valid = bool(text.strip())  # v0.1: non-empty. Grammar-level
                                            # validation arrives with the adapter.
                h = store.add_input(gi.data, gi.generator, valid=valid, gen_cost_ms=gi.cost_ms)
                origins.setdefault(h, set()).add(gi.generator)
                produced.append((h, gi.generator))
                if valid:
                    items.append(Item(blob_hash=h, text=text, generator=gi.generator))
            store.commit()
            # Which inputs each source produced in THIS run, in order: the store is content-
            # addressed across runs, so without this list a run's own inputs could not be
            # replayed later (`spreadex record`) without regenerating them.
            with open(run_dir / "inputs.jsonl", "w") as fh:
                for h, g in produced:
                    fh.write(json.dumps({"blob": h, "generator": g}) + "\n")
            # De-duplicate by content: the same program from two generators is
            # one unit of execution budget, not two.
            seen: set[str] = set()
            unique: list[Item] = []
            for it in items:
                if it.blob_hash not in seen:
                    seen.add(it.blob_hash)
                    unique.append(it)
            items = unique
            result.valid = len(items)
            for gi in generated:
                result.generator_counts[gi.generator] = \
                    result.generator_counts.get(gi.generator, 0) + 1
                result.generator_cost_ms[gi.generator] = \
                    result.generator_cost_ms.get(gi.generator, 0.0) + gi.cost_ms
            self.log(f"  {result.generated} generated -> {result.valid} valid, unique")

            # 3. Signals + 4. Prioritize -------------------------------------
            self.log(f"Ranking with signal {signal_name!r}...")
            signal = make_signal(signal_name, cfg.embedding.get("model", "tfidf"))
            ordering = signal.rank(items, seed=cfg.seed)
            result.generator_scores = ordering.generator_scores
            result.k_eff = ordering.k_eff
            ordered = [items[i] for i in ordering.order]
            selection = None
            if cfg.selection.get("keep") == "all":
                pass                        # every generator is kept; CC is reported, not used to choose
            elif cfg.selection and signal_name != "cc":
                self.log("  selection: needs the cc signal to score generators, so every input is kept")
            elif cfg.selection and ordering.generator_scores:
                picked = choose_generators(ordering.generator_scores, cfg.generators, cfg.selection["keep"])
                if picked is None:
                    self.log(f"  selection: fewer than {cfg.selection['keep'] + 1} generators produced "
                             f"inputs, so every input is kept")
                else:
                    before = len(ordered)
                    ordered = apply_selection(ordered, origins, picked[1])
                    selection = Selection(keep=cfg.selection["keep"], selected=picked[0], dropped=picked[1],
                                          scores={g: round(ordering.generator_scores[g], 4) for g in picked[0] + picked[1]},
                                          kept_inputs=len(ordered), dropped_inputs=before - len(ordered))
            if cfg.budget.max_inputs:
                ordered = ordered[: cfg.budget.max_inputs]
            result.prioritized = len(ordered)
            if ordering.generator_scores:
                pretty = ", ".join(f"{g} {v:.2f}" for g, v in sorted(ordering.generator_scores.items()))
                self.log(f"  cluster coverage: {pretty}  (k_eff={ordering.k_eff})")
            for caveat in getattr(ordering, "caveats", []):
                # Wrapped by hand: this is the one place the tool admits its own
                # measurement is shaky, and it should not scroll past as one line.
                self.log("  ! " + caveat.replace(". ", ".\n    "))
            result.signal_caveats = list(getattr(ordering, "caveats", []))
            if selection is not None:
                self.log(selection.log_line())
                result.selection = selection.as_dict()

            # 5-8. Execute / Observe / Oracle / Persist -----------------------
            oracle = make_oracle(cfg.oracle)
            clock = Clock(cfg.budget.execution_s)
            self.log(f"Executing against {len(cfg.targets)} target(s), "
                     f"budget {cfg.budget.execution_s:.0f}s...")

            failures_so_far = 0
            sigs_so_far: set[str] = set()

            input_files = InputFiles(cfg.input_extension)

            def execute(item):
                """Run one input against every target. Pure: no store access."""
                path = input_files.path(item.blob_hash, store.blob_path(item.blob_hash))
                observations = [run_one(t, path, input_hash=item.blob_hash) for t in cfg.targets]
                return observations, oracle.judge(observations)

            # Set when the system under test could not be started at all (a missing program,
            # runtime or working directory, or the launcher's own "could not start" message on the
            # first input). That is a failed campaign, not a finding: every input would otherwise
            # be recorded as a crash or the run would end early looking finished.
            startup_error: list[str] = []

            def check_started(observations) -> bool:
                """On the first input only: did the system start? Records why not.

                A launcher's "could not start" wording can also be ordinary output of the system
                under test (a generated program that prints it, an interpreter reporting a missing
                module). So a match is confirmed by running the same command on an EMPTY input:
                only a failure that does not depend on the input is an infrastructure failure.
                """
                if result.executed:
                    return True
                import tempfile

                from ..exec.setup_check import setup_failure

                for t, obs in zip(cfg.targets, observations):
                    why = setup_failure(obs, t)
                    if not why:
                        continue
                    with tempfile.TemporaryDirectory() as tmp:
                        empty = Path(tmp) / f"empty{cfg.input_extension or ''}"
                        empty.write_bytes(b"")
                        try:
                            again = setup_failure(run_one(t, empty), t)
                        except RuntimeError as exc:
                            again = str(exc)
                    if again:
                        startup_error.append(f"target {t.name!r} did not start: {why}")
                        return False
                    self.log(f"  note: the first input's output looks like a launcher error ({why}), "
                             f"but the same command ran on an empty input, so it is treated as the "
                             f"system's own output")
                return True

            def persist(rank, item, observations, judgement) -> None:
                nonlocal failures_so_far
                store.record_execution(run_id, item.blob_hash, rank, observations, judgement)
                result.executed += 1
                if judgement.is_failure:
                    failures_so_far += 1
                    if judgement.signature:
                        sigs_so_far.add(judgement.signature)
                result.budget_curve.append((result.executed, len(sigs_so_far)))
                # Often enough that the UI's live view (which reads the database) moves, rarely enough
                # that committing is not the cost of an execution.
                if result.executed % 10 == 0:
                    store.commit()

            if jobs <= 1:
                for rank, item in enumerate(ordered):
                    if clock.exhausted():
                        self.log(f"  execution budget exhausted after {rank} inputs")
                        break
                    if self.cancelled():
                        break
                    try:
                        observations, judgement = execute(item)
                    except RuntimeError as exc:
                        startup_error.append(str(exc))
                        break
                    if not check_started(observations):
                        break
                    persist(rank, item, observations, judgement)
            else:
                # Subprocess execution is I/O-bound from Python's side, so threads
                # are enough. Results are persisted in completion order but keep
                # their original rank, so the prioritized order is still recorded.
                # NOTE: under contention, duration_ms is noisier and a marginal
                # input can time out that would have passed serially -- which is
                # why jobs defaults to 1.
                from concurrent.futures import ThreadPoolExecutor, FIRST_COMPLETED, wait

                pending: dict = {}
                it = enumerate(ordered)
                stop = False
                with ThreadPoolExecutor(max_workers=jobs) as pool:
                    while not stop or pending:
                        while not stop and len(pending) < jobs:
                            if clock.exhausted() or self.cancelled():
                                stop = True
                                break
                            nxt = next(it, None)
                            if nxt is None:
                                stop = True
                                break
                            rank, item = nxt
                            pending[pool.submit(execute, item)] = (rank, item)
                        if not pending:
                            break
                        done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                        for fut in done:
                            rank, item = pending.pop(fut)
                            try:
                                observations, judgement = fut.result()
                            except RuntimeError as exc:
                                if not startup_error:
                                    startup_error.append(str(exc))
                                stop = True
                                continue
                            if startup_error or not check_started(observations):
                                stop = True
                                continue
                            persist(rank, item, observations, judgement)
                if clock.exhausted():
                    self.log(f"  execution budget exhausted after {result.executed} inputs")

            store.commit()
            if startup_error:
                # Recorded as a failed run (so history shows it), then raised: the CLI exits non-zero
                # and the Workbench reports it, instead of either calling this a completed campaign.
                manifest.results = {"executed": result.executed, "error": startup_error[0]}
                manifest.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                manifest.write(run_dir / "manifest.json")
                store.finish_run(run_id, manifest_hash=manifest.hash(), status="failed")
                raise CampaignStartupError(
                    f"The campaign failed: the system under test could not be started.\n  {startup_error[0]}\n"
                    f"  Nothing was tested. Fix the command or install what it needs, then check with "
                    f"`spreadex doctor`.")
            if self.cancelled():
                self.log(f"  cancelled after {result.executed} inputs")
            result.exec_elapsed_s = clock.elapsed()
            result.verdicts = store.run_summary(run_id)
            result.signatures = [
                (r["signature"], r["verdict"], r["n"]) for r in store.signatures_in_run(run_id)
            ]
            result.new_signatures = store.new_signatures(run_id)

            store.write_results_jsonl(run_id)
            manifest.corpus = {
                "generated": result.generated,
                "valid": result.valid,
                "prioritized": result.prioritized,
                "generator_scores": result.generator_scores,
                "generator_counts": result.generator_counts,
                "generator_cost_ms": result.generator_cost_ms,
                "k_eff": result.k_eff,
                "signal_caveats": result.signal_caveats,
                "generation_stats": result.generation_stats,
                "selection": result.selection,
                "generation_mode": (cfg.raw.get("generation") or {}).get("mode", "count"),
                "grammars": _grammar_provenance(cfg),
                "allocation_s": allocation,
            }
            manifest.results = {
                "budget_curve": result.budget_curve,
                "executed": result.executed,
                "verdicts": result.verdicts,
                "signatures": [s[0] for s in result.signatures],
                "new_signatures": result.new_signatures,
            }
            manifest.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            mh = manifest.hash()
            manifest.write(run_dir / "manifest.json")
            store.finish_run(run_id, manifest_hash=mh,
                             status="cancelled" if self.cancelled() else "finished")

        return result


class CampaignStartupError(RuntimeError):
    """The system under test could not be started, so the campaign tested nothing."""


def _target_provenance(t) -> dict:
    """How a target was run, and -- for a pinned runtime -- exactly which artifact ran."""
    from .. import runtimes

    used = sorted({r for part in t.command for r in runtimes.references(part)})
    pinned = []
    for name in used:
        rt = runtimes.get(name)
        pinned.append({"name": rt.name, "title": rt.title, "version": rt.version, "url": rt.url,
                       "sha256": rt.sha256, "licence": rt.licence,
                       "verified": runtimes.verified(name) is not None})
    version = t.version or (f"{pinned[0]['title']} {pinned[0]['version']}" if pinned
                            else probe_target_version(t.command))
    out = {"name": t.name, "command": t.command, "version": version, "timeout_s": t.limits.timeout_s}
    if pinned:
        out["runtimes"] = pinned
    return out


def _grammar_provenance(cfg) -> dict:
    """Each generator's grammar file and the sha256 of its content (replayed ones have none)."""
    import hashlib

    try:
        replayed = sources.recorded_sources(cfg)
    except Exception:
        replayed = {}
    out = {}
    for gid in cfg.generators or []:
        if gid in replayed:
            continue
        path = sources.grammar_for(cfg, gid)
        if path is not None and path.is_file():
            try:
                rel = str(path.relative_to(cfg.project_root))
            except ValueError:
                rel = str(path)
            out[gid] = {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return out
