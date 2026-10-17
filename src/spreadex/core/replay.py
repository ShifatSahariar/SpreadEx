"""Replay a recorded campaign: the same inputs, in the same order, against the same configuration.

A replay never generates, embeds, clusters or prioritizes. It reads which inputs the source run
executed and at which rank (the `executions` table, which every run has, however old), and executes
exactly those inputs in exactly that order with the targets and oracle the source run recorded in its
manifest. The result is a separate run, marked `replay_of`; the source run is never touched.

Regenerating ("run again") is a different operation: new inputs, a new diversity map, the current
prioritization variant. It lives in Campaign.run and is always asked for explicitly.

The whole recorded sequence is executed, whatever the source run's time budget was: a slower or
faster machine must not change which inputs a replay covers. Cancelling stops it early.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from .. import __version__
from ..corpus import CorpusStore
from ..exec import run_one
from ..exec.inputs import InputFiles
from ..exec.oracle import make_oracle
from .config import Config, ConfigError, load_config
from .lock import RunLock
from .manifest import Manifest, capture_environment


class ReplayError(RuntimeError):
    """The run cannot be replayed; the message says why."""


def recorded_sequence(store: CorpusStore, run_id: str) -> list[str]:
    """The inputs a run executed, in the order it executed them (one per rank)."""
    rows = store.conn.execute(
        "SELECT rank, blob_hash FROM executions WHERE run_id=? ORDER BY rank", (run_id,)).fetchall()
    seen: set[int] = set()
    out: list[str] = []
    for r in rows:
        if r["rank"] in seen:            # one row per target in a differential campaign
            continue
        seen.add(r["rank"])
        out.append(r["blob_hash"])
    return out


def recorded_verdicts(store: CorpusStore, run_id: str) -> dict[str, str]:
    rows = store.conn.execute(
        "SELECT blob_hash, verdict FROM executions WHERE run_id=? ORDER BY rank", (run_id,)).fetchall()
    return {r["blob_hash"]: r["verdict"] for r in rows}


def load_manifest(state_dir: Path, run_id: str) -> dict:
    path = Path(state_dir) / "runs" / run_id / "manifest.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise ReplayError(f"run {run_id} has no readable manifest") from None


def config_from_manifest(project_root: Path, manifest: dict) -> Config:
    """The configuration a run recorded, loaded as the CLI would load it.

    Relative paths resolve against the project, so the copy is parsed from the project root and
    removed straight after. A run recorded without a `prioritization` block is not given one here:
    for a replay it does not matter (nothing is prioritized), and for a regeneration the caller is
    told the current default will be used.
    """
    raw = manifest.get("config")
    if not raw:
        raise ReplayError(f"run {manifest.get('run_id')} recorded no configuration")
    fd, tmp = tempfile.mkstemp(prefix=".spreadex-replay-", suffix=".yaml", dir=project_root)
    try:
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(raw, fh)
        return load_config(Path(tmp))
    except ConfigError as exc:
        raise ReplayError(str(exc)) from None
    finally:
        os.unlink(tmp)


def recorded_prioritization(manifest: dict) -> dict:
    """What the source run says about its ordering; 'unknown' when it says nothing."""
    return (manifest.get("corpus") or {}).get("prioritization") or {"variant": "unknown"}


def replay(project_root: Path, state_dir: Path, source_run_id: str, *,
           log: Callable[[str], None] = print, stop_event: threading.Event | None = None,
           origin: str = "cli", run_id: str | None = None) -> dict:
    """Execute the source run's recorded sequence as a new run. Returns a summary."""
    from .campaign import new_run_id

    stop_event = stop_event or threading.Event()
    manifest = load_manifest(state_dir, source_run_id)
    config = config_from_manifest(project_root, manifest)
    with CorpusStore(state_dir) as store:
        sequence = recorded_sequence(store, source_run_id)
        before = recorded_verdicts(store, source_run_id)
        missing = [h for h in sequence if not store.blob_path(h).is_file()]
    if not sequence:
        raise ReplayError(f"run {source_run_id} executed no inputs, so there is nothing to replay")
    if missing:
        raise ReplayError(f"{len(missing)} of the run's inputs are missing from the corpus store")

    lock = RunLock(state_dir)
    lock.acquire(origin=origin)
    try:
        with CorpusStore(state_dir) as store:
            store.mark_abandoned()
            run_id = run_id or store.unique_run_id(new_run_id())
            lock.set_run(run_id)
            run_dir = store.start_run(run_id, config_hash=config.hash(), seed=config.seed,
                                      gen_budget_s=0.0, exec_budget_s=None,
                                      signal_name=f"replay of {source_run_id}", origin=origin)
            log(f"Replaying {len(sequence)} recorded inputs of {source_run_id} in their recorded order "
                f"(no generation, no prioritization)...")
            oracle = make_oracle(config.oracle)
            files = InputFiles(config.input_extension)
            agree, differ, curve, sigs = 0, [], [], set()
            executed = 0
            status = "finished"
            for rank, blob in enumerate(sequence):
                if stop_event.is_set():
                    status = "cancelled"
                    break
                path = files.path(blob, store.blob_path(blob))
                observations = [run_one(t, path, input_hash=blob) for t in config.targets]
                judgement = oracle.judge(observations)
                store.record_execution(run_id, blob, rank, observations, judgement)
                executed += 1
                if judgement.is_failure and judgement.signature:
                    sigs.add(judgement.signature)
                curve.append((executed, len(sigs)))
                if before.get(blob) == judgement.verdict.value:
                    agree += 1
                else:
                    differ.append({"rank": rank, "blob": blob, "recorded": before.get(blob),
                                   "replayed": judgement.verdict.value})
                if executed % 10 == 0:
                    store.commit()
            store.commit()
            store.write_results_jsonl(run_id)
            summary = {"replay_of": source_run_id, "ordering": "recorded",
                       "source_prioritization": recorded_prioritization(manifest),
                       "inputs": len(sequence), "executed": executed,
                       "same_verdict": agree, "different_verdict": differ[:50],
                       "different_count": len(differ)}
            out = Manifest(run_id=run_id, spreadex_version=__version__, config_hash=config.hash(),
                           config=manifest.get("config") or {}, semantics=manifest.get("semantics") or {},
                           seed=config.seed, signal=f"replay of {source_run_id}",
                           started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           effective={"replay_of": source_run_id},
                           environment=capture_environment(), targets=manifest.get("targets", []))
            out.corpus = {"replay": summary, "prioritization": summary["source_prioritization"]}
            out.results = {"budget_curve": curve, "executed": executed,
                           "verdicts": store.run_summary(run_id),
                           "signatures": [r["signature"] for r in store.signatures_in_run(run_id)],
                           "new_signatures": store.new_signatures(run_id)}
            out.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            out.write(run_dir / "manifest.json")
            store.finish_run(run_id, manifest_hash=out.hash(), status=status)
        log(f"  {agree} of {executed} replayed inputs have their recorded verdict"
            + (f"; {len(differ)} differ" if differ else ""))
        return {"run_id": run_id, **summary}
    finally:
        lock.release()


# ------------------------------------------------- from an export (no store, no SUT)

def manifest_from_export(zip_path: Path) -> dict:
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        return json.loads(z.read("run/manifest.json"))


def sequence_from_export(zip_path: Path) -> list[str]:
    """The recorded execution order of an exported run, from its results.jsonl (one per rank)."""
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        rows = [json.loads(l) for l in z.read("run/results.jsonl").decode().splitlines() if l.strip()]
    by_rank: dict[int, str] = {}
    for r in rows:
        by_rank.setdefault(int(r["rank"]), r["blob_hash"])
    return [by_rank[k] for k in sorted(by_rank)]
