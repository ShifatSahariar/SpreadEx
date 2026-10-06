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


# ===================================================================== results workspace
#
# Everything below is derived from what a run actually recorded: the executions table, the inputs it
# ran, the failures table and the manifest. Nothing is estimated and nothing is invented; a number
# the run did not record (coverage, mutation score, cost) is simply not here.

FAILURES = ("crash", "timeout", "divergence")


def _exec_rows(store: CorpusStore, run_id: str) -> list[dict[str, Any]]:
    """One row per executed input, in execution order. With several targets an input has several
    rows; they share a verdict, and the slowest duration is the one that matters."""
    rows = store.conn.execute(
        """SELECT e.blob_hash, e.rank, e.verdict, e.signature, e.detail, e.exit_code, e.signal,
                  e.timed_out, e.duration_ms, e.sut_id, i.generator, i.size_bytes
           FROM executions e JOIN inputs i ON i.blob_hash = e.blob_hash
           WHERE e.run_id=? ORDER BY e.rank, e.sut_id""", (run_id,)).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cur = out.get(r["blob_hash"])
        if cur is None:
            out[r["blob_hash"]] = dict(r)
        elif (r["duration_ms"] or 0) > (cur["duration_ms"] or 0):
            cur["duration_ms"] = r["duration_ms"]
    return sorted(out.values(), key=lambda d: d["rank"])


def _findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Failures grouped by signature, numbered F-001... in the order they were first reached."""
    groups: dict[str, dict[str, Any]] = {}
    for pos, r in enumerate(rows):
        if r["verdict"] not in FAILURES or not r["signature"]:
            continue
        g = groups.get(r["signature"])
        if g is None:
            groups[r["signature"]] = {
                "signature": r["signature"], "verdict": r["verdict"], "count": 1, "position": pos,
                "first_rank": r["rank"], "example": r["blob_hash"], "generator": r["generator"],
                "duration_ms": r["duration_ms"], "detail": r["detail"], "generators": {r["generator"]},
            }
        else:
            g["count"] += 1
            g["generators"].add(r["generator"])
    ordered = sorted(groups.values(), key=lambda g: g["position"])
    for i, g in enumerate(ordered, 1):
        g["id"] = f"F-{i:03d}"
        g["generators"] = sorted(g["generators"])
    return ordered


def _generator_breakdown(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    corpus = manifest.get("corpus", {}) or {}
    scores = corpus.get("generator_scores", {}) or {}
    counts = corpus.get("generator_counts", {}) or {}
    stats = {s.get("generator"): s for s in (corpus.get("generation_stats") or [])}
    names = sorted(set(scores) | set(counts) | set(stats) | {r["generator"] for r in rows})
    findings = _findings(rows)
    out = []
    for name in names:
        mine = [r for r in rows if r["generator"] == name]
        by = {v: sum(1 for r in mine if r["verdict"] == v)
              for v in ("ok", "expected_rejection", "crash", "timeout", "divergence")}
        st = stats.get(name) or {}
        out.append({
            "name": name,
            "generated": st.get("produced", counts.get(name, 0)),
            "valid": counts.get(name, 0),
            "executed": len(mine),
            "verdicts": by,
            "findings": sum(1 for f in findings if f["generator"] == name),
            "pass_rate": (by["ok"] / len(mine)) if mine else None,
            "cc": scores.get(name),
            "gen_requested_s": st.get("requested_seconds"),
            "gen_elapsed_s": st.get("elapsed_s"),
            "avg_ms": (sum((r["duration_ms"] or 0) for r in mine) / len(mine)) if mine else None,
        })
    return sorted(out, key=lambda g: -g["executed"])


def _timeline(rows: list[dict[str, Any]], bins: int = 40) -> list[dict[str, Any]]:
    """Outcomes in execution ORDER. Executions can run in parallel, so this is position, not wall time."""
    if not rows:
        return []
    size = max(1, -(-len(rows) // bins))
    out = []
    for start in range(0, len(rows), size):
        chunk = rows[start:start + size]
        c = {v: sum(1 for r in chunk if r["verdict"] == v)
             for v in ("ok", "expected_rejection", "crash", "timeout", "divergence")}
        out.append({"from": start + 1, "to": start + len(chunk), **c})
    return out


def _prioritization(rows: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n or not findings:
        return {"executed": n, "findings": len(findings), "first_at": None, "by_quarter": None, "by_half": None, "all_at": None}
    pos = sorted(f["position"] + 1 for f in findings)      # 1-based position of each first sighting
    return {"executed": n, "findings": len(findings), "first_at": pos[0],
            "by_quarter": sum(1 for p in pos if p <= n / 4), "by_half": sum(1 for p in pos if p <= n / 2),
            "all_at": pos[-1], "all_pct": round(100 * pos[-1] / n)}


def results_overview(state_dir: Path, run_id: str) -> dict[str, Any] | None:
    """The workspace payload: everything the five tabs show, computed once."""
    base = run_detail(state_dir, run_id)
    if base is None:
        return None
    with CorpusStore(state_dir) as store:
        manifest = _manifest(store, run_id)
        rows = _exec_rows(store, run_id)
        stderr = {r["signature"]: r["example_stderr"] for r in store.conn.execute(
            "SELECT signature, example_stderr FROM failures").fetchall()}
        all_runs = [r["run_id"] for r in store.conn.execute("SELECT run_id FROM runs ORDER BY started_at").fetchall()]
    findings = _findings(rows)
    for f in findings:
        f["stderr_first"] = ((stderr.get(f["signature"]) or "").strip().splitlines() or [""])[0]
    started, finished = base.get("started_at"), base.get("finished_at")
    duration = None
    if started and finished:
        from datetime import datetime
        try:
            duration = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
        except ValueError:
            duration = None
    corpus = manifest.get("corpus", {}) or {}
    base.update({
        "number": all_runs.index(run_id) + 1 if run_id in all_runs else None,
        "complete": bool(finished),
        "duration_s": duration,
        "findings": findings,
        "by_generator": _generator_breakdown(rows, manifest),
        "timeline": _timeline(rows),
        "prioritization": _prioritization(rows, findings),
        "generation_stats": corpus.get("generation_stats") or [],
        "generation_mode": corpus.get("generation_mode"),
        "oracle": (manifest.get("config") or {}).get("oracle") or {},
        "exec_cpu_s": sum((r["duration_ms"] or 0) for r in rows) / 1000,
        "runs": all_runs,
    })
    return base


def run_inputs(state_dir: Path, run_id: str, *, q: str = "", generator: str = "", verdict: str = "",
               offset: int = 0, limit: int = 10) -> dict[str, Any] | None:
    """The executed inputs of a run, filterable. Inputs that were generated but never reached are
    counted in the overview, not listed: a run does not record which of the corpus's inputs it
    considered, only which it executed."""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    with CorpusStore(state_dir) as store:
        if store.conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
            return None
        rows = _exec_rows(store, run_id)
        ids = {f["signature"]: f["id"] for f in _findings(rows)}
        facets = {"generators": {}, "verdicts": {}}
        for r in rows:
            facets["generators"][r["generator"]] = facets["generators"].get(r["generator"], 0) + 1
            facets["verdicts"][r["verdict"]] = facets["verdicts"].get(r["verdict"], 0) + 1
        picked = [r for r in rows if (not generator or r["generator"] == generator)
                  and (not verdict or r["verdict"] == verdict)]
        needle = (q or "").strip().lower()

        def text_of(h: str) -> str:
            try:
                return store.get_blob(h).decode("utf-8", errors="replace")
            except OSError:
                return ""

        if needle:
            hit = []
            for r in picked[:5000]:                     # a bounded scan: inputs are small, but not unlimited
                if r["blob_hash"].startswith(needle) or needle in text_of(r["blob_hash"]).lower():
                    hit.append(r)
            picked = hit
        page = picked[offset:offset + limit]
        items = [{
            "rank": r["rank"], "hash": r["blob_hash"], "generator": r["generator"], "verdict": r["verdict"],
            "finding": ids.get(r["signature"]) if r["verdict"] in FAILURES else None,
            "size": r["size_bytes"], "duration_ms": r["duration_ms"],
            "preview": " ".join(text_of(r["blob_hash"])[:90].split()),
        } for r in page]
    return {"total": len(picked), "all": len(rows), "offset": offset, "limit": limit, "items": items, "facets": facets}


def classification_evidence(oracle: dict, f: dict[str, Any], stderr: str) -> list[dict[str, str]]:
    """WHY the engine called this what it did, in the engine's own order. Read from the recorded
    verdict and detail plus the configured patterns -- no model, nothing guessed."""
    import re

    verdict, detail = f["verdict"], f.get("detail") or ""
    timed_out = verdict == "timeout"
    signalled = verdict == "crash" and detail.startswith("signal")
    crash_pats = [p for p in (oracle.get("crash_patterns") or []) if isinstance(p, str)]
    rej_pats = [p for p in (oracle.get("rejection_patterns") or []) if isinstance(p, str)]

    def hits(pats):
        out = []
        for p in pats:
            try:
                if re.search(p, stderr or "", re.IGNORECASE | re.MULTILINE):
                    out.append(p)
            except re.error:
                pass
        return out

    checks: list[dict[str, str]] = []
    checks.append({"rule": "Timeout", "status": "matched" if timed_out else "no",
                   "note": (detail or "No answer in time") if timed_out else "Not a timeout"})
    if verdict == "divergence":
        checks.append({"rule": "Implementations disagree", "status": "matched", "note": detail})
        return checks
    checks.append({"rule": "Killed by a signal", "status": "matched" if signalled else "no",
                   "note": detail if signalled else "No signal"})
    crash_hit = "matched a crash pattern" in detail
    matched = hits(crash_pats) if crash_hit else []
    checks.append({"rule": "Crash pattern", "status": "matched" if crash_hit else "no",
                   "note": (matched[0] if matched else "matched in the output") if crash_hit
                   else ("No match" if crash_pats else "None configured")})
    rej = hits(rej_pats)
    checks.append({"rule": "Expected rejection", "status": "no",
                   "note": "No match" if rej_pats else "None configured"} if not rej else
                  {"rule": "Expected rejection", "status": "no", "note": f"{rej[0]} matched, but a failure rule came first"})
    if verdict == "crash" and not (timed_out or signalled or crash_hit):
        checks.append({"rule": "Unexpected non-zero exit", "status": "matched",
                       "note": f"{detail or 'non-zero exit'} is not an expected exit code"})
    return checks


def finding_detail(state_dir: Path, run_id: str, signature: str) -> dict[str, Any] | None:
    with CorpusStore(state_dir) as store:
        if store.conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
            return None
        manifest = _manifest(store, run_id)
        rows = _exec_rows(store, run_id)
        findings = _findings(rows)
        f = next((x for x in findings if x["signature"] == signature), None)
        if f is None:
            return None
        row = store.conn.execute("SELECT example_stderr FROM failures WHERE signature=?", (signature,)).fetchone()
        stderr = (row["example_stderr"] if row else "") or ""
        ex = next(r for r in rows if r["blob_hash"] == f["example"])
        similar = [r for r in rows if r["signature"] == signature and r["blob_hash"] != f["example"]]
        text = store.get_blob(f["example"]).decode("utf-8", errors="replace")
        oracle = (manifest.get("config") or {}).get("oracle") or {}
        sims = []
        for r in similar[:5]:
            try:
                prev = " ".join(store.get_blob(r["blob_hash"]).decode("utf-8", errors="replace")[:70].split())
            except OSError:
                prev = ""
            sims.append({"hash": r["blob_hash"], "rank": r["rank"], "generator": r["generator"], "preview": prev})
        index = findings.index(f)
    return {
        "id": f["id"], "number": index + 1, "of": len(findings), "signature": signature, "verdict": f["verdict"],
        "headline": (stderr.strip().splitlines() or [f["detail"] or f["verdict"]])[0],
        "detail": f["detail"], "count": f["count"], "generator": f["generator"], "generators": f["generators"],
        "first_rank": f["first_rank"], "hash": f["example"], "input": text[:20000],
        "exit_code": ex["exit_code"], "signal": ex["signal"], "timed_out": bool(ex["timed_out"]),
        "duration_ms": ex["duration_ms"], "stderr": stderr[:8000], "size": ex["size_bytes"],
        "evidence": classification_evidence(oracle, {**f, "detail": f["detail"]}, stderr),
        "similar": sims, "similar_total": len(similar),
    }
