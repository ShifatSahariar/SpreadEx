"""Read-only views over a project's corpus, shaped for the browser UI.

The UI is a VIEW, not a controller: it reads `.spreadex/` and never starts,
stops or changes a campaign. That keeps the browser out of the trust path for
anything that executes code, and it means every number on screen came from the
same files the CLI reports from.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from ..corpus import CorpusStore

MAX_INPUT_CHARS = 4000
RANDOM_TRIALS = 200


def _manifest(store: CorpusStore, run_id: str) -> dict[str, Any]:
    path = store.run_dir(run_id) / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def list_runs(state_dir: Path) -> list[dict[str, Any]]:
    with CorpusStore(state_dir) as store:
        out = []
        for row in store.list_runs(limit=200):
            summary = store.run_summary(row["run_id"])
            executed = sum(summary.values())
            failures = sum(summary.get(k, 0) for k in ("crash", "timeout", "divergence"))
            out.append({
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "signal": row["signal_name"],
                "seed": row["seed"],
                "executed": executed,
                "failures": failures,
                "verdicts": summary,
                "complete": bool(row["finished_at"]),
            })
        return out


def run_detail(state_dir: Path, run_id: str) -> dict[str, Any] | None:
    with CorpusStore(state_dir) as store:
        row = store.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        manifest = _manifest(store, run_id)
        corpus = manifest.get("corpus", {})
        results = manifest.get("results", {})

        generators = []
        scores = corpus.get("generator_scores", {}) or {}
        counts = corpus.get("generator_counts", {}) or {}
        costs = corpus.get("generator_cost_ms", {}) or {}
        for name in sorted(scores, key=lambda n: -scores[n]):
            generators.append({
                "name": name,
                "cc": scores[name],
                "inputs": counts.get(name, 0),
                "cost_s": (costs.get(name, 0.0) or 0.0) / 1000,
            })

        summary = store.run_summary(run_id)
        curve = results.get("budget_curve") or []
        return {
            "run_id": run_id,
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "signal": row["signal_name"],
            "seed": row["seed"],
            "config_hash": row["config_hash"],
            "budgets": manifest.get("effective", {}),
            "targets": manifest.get("targets", []),
            "environment": manifest.get("environment", {}),
            "corpus": {
                "generated": corpus.get("generated"),
                "valid": corpus.get("valid"),
                "prioritized": corpus.get("prioritized"),
                "k_eff": corpus.get("k_eff"),
                "signal_caveats": corpus.get("signal_caveats", []),
            },
            "generators": generators,
            "verdicts": summary,
            "executed": sum(summary.values()),
            "budget_curve": curve,
            "random_curve": random_baseline_curve(store, run_id),
            "signatures": signatures(store, run_id),
            "new_signatures": results.get("new_signatures", []),
        }


def signatures(store: CorpusStore, run_id: str) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """SELECT e.signature, e.verdict, COUNT(DISTINCT e.blob_hash) n,
                  MIN(e.rank) first_rank, MIN(e.blob_hash) example,
                  MAX(e.detail) detail
           FROM executions e
           WHERE e.run_id=? AND e.signature IS NOT NULL
                 AND e.verdict IN ('crash','timeout','divergence')
           GROUP BY e.signature, e.verdict
           ORDER BY n DESC""",
        (run_id,),
    ).fetchall()
    out = []
    for row in rows:
        failure = store.conn.execute(
            "SELECT first_seen_run, example_stderr FROM failures WHERE signature=?",
            (row["signature"],),
        ).fetchone()
        out.append({
            "signature": row["signature"],
            "verdict": row["verdict"],
            "count": row["n"],
            "first_rank": row["first_rank"],
            "example": row["example"],
            "detail": row["detail"],
            "stderr": (failure["example_stderr"] if failure else None),
            "new": bool(failure and failure["first_seen_run"] == run_id),
        })
    return out


def random_baseline_curve(store: CorpusStore, run_id: str) -> list[list[int]]:
    """How many distinct signatures random ordering would have found by now.

    The same executed inputs, reshuffled: this isolates the ORDERING, which is
    the only thing prioritization controls. Averaged over several hundred
    shuffles, so a single lucky permutation cannot flatter either side.
    """
    rows = store.conn.execute(
        """SELECT DISTINCT blob_hash, signature FROM executions
           WHERE run_id=? AND verdict IN ('crash','timeout','divergence')
                 AND signature IS NOT NULL""",
        (run_id,),
    ).fetchall()
    total = store.conn.execute(
        "SELECT COUNT(DISTINCT blob_hash) c FROM executions WHERE run_id=?", (run_id,)
    ).fetchone()["c"]
    if not rows or not total:
        return []

    labels = [r["signature"] for r in rows]
    rng = random.Random(0)
    sums = [0.0] * (total + 1)
    for _ in range(RANDOM_TRIALS):
        positions = rng.sample(range(total), len(labels))
        placed = sorted(zip(positions, labels))
        seen: set[str] = set()
        idx = 0
        for position in range(total):
            while idx < len(placed) and placed[idx][0] == position:
                seen.add(placed[idx][1])
                idx += 1
            sums[position + 1] += len(seen)
    return [[i, round(sums[i] / RANDOM_TRIALS, 3)] for i in range(1, total + 1)]


def input_text(state_dir: Path, blob_hash: str) -> dict[str, Any] | None:
    with CorpusStore(state_dir) as store:
        path = store.blob_path(blob_hash)
        if not path.exists():
            return None
        data = path.read_bytes()
        row = store.conn.execute(
            "SELECT generator, size_bytes FROM inputs WHERE blob_hash=?", (blob_hash,)
        ).fetchone()
        return {
            "blob_hash": blob_hash,
            "generators": store.generators_of(blob_hash),
            "size_bytes": row["size_bytes"] if row else len(data),
            "text": data[:MAX_INPUT_CHARS].decode("utf-8", errors="replace"),
            "truncated": len(data) > MAX_INPUT_CHARS,
        }


def grammar_report(config, source_override: str | None = None) -> dict[str, Any]:
    """Static grammar diagnostics and per-generator expressibility."""
    from ..core.sources import grammar_for

    if source_override:
        candidate = (config.project_root / source_override).resolve()
        if not candidate.is_file() or config.project_root.resolve() not in candidate.parents:
            return {"configured": True, "source": source_override,
                    "error": "that grammar is not inside this project"}
        return _report_for(config, candidate)

    sources: dict[str, str] = {}
    for generator in config.generators or []:
        path = grammar_for(config, generator)
        if path:
            sources.setdefault(str(path), "")
    single = (config.grammar or {}).get("source")
    if single:
        sources.setdefault(str((config.project_root / single).resolve()), "")
    if not sources:
        return {"configured": False}

    return _report_for(config, Path(next(iter(sources))))


def _report_for(config, path: Path) -> dict[str, Any]:
    from ..grammar import RENDERERS, GrammarError, diagnose, expressibility, load

    try:
        grammar = load(path)
    except (GrammarError, OSError) as exc:
        return {"configured": True, "source": str(path), "error": str(exc)}

    report = diagnose(grammar)
    support = []
    for generator in sorted(config.generators or RENDERERS):
        if generator not in RENDERERS:
            support.append({"generator": generator, "status": "unsupported",
                            "detail": "SpreadEx cannot emit this dialect"})
            continue
        exp = expressibility(grammar, generator)
        support.append({
            "generator": generator,
            "status": "direct" if exp.directly else ("rewrite" if exp.usable else "blocked"),
            "missing": sorted(f.value for f in exp.missing),
            "blockers": exp.blockers,
            "risks": exp.risks,
        })
    return {
        "configured": True,
        "source": str(path),
        # The assistant writes constraints against these symbols, so it needs
        # the grammar itself, not only a summary of it.
        "text": path.read_text(errors="replace")[:40000],
        "rules": len(grammar.rules),
        "alternatives": sum(len(n.options) if hasattr(n, "options") else 1
                            for n in grammar.rules.values()),
        "start": grammar.start,
        "features": sorted(f.value for f in grammar.features()),
        "findings": [
            {"severity": f.severity.value, "code": f.code, "message": f.message,
             "rule": f.rule, "fix": f.fix}
            for f in report.findings
        ],
        "support": support,
    }
