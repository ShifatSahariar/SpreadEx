"""The budget curve is by priority rank, whatever order parallel jobs finish in.

With `-j N` a later rank can finish before an earlier one. The curve (and everything read from it:
signature first positions, the Budget view, the CLI's "first failure at input") must agree with
the rank-based reports, so it is compared with the curve rebuilt from the stored executions.
"""

import json
import shutil
from pathlib import Path

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.corpus import CorpusStore
from spreadex.corpus.store import rank_curve

TOY = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"

# The toy parser, except that a crashing input is slow: every input ranked just after it
# finishes first, so completion order and rank order disagree exactly where it matters.
SLOW_CRASH_PARSER = '''\
import sys, time
src = open(sys.argv[1]).read().strip()
tokens = src.split()
if not tokens or tokens[0] != "let":
    sys.stderr.write("SyntaxError: expected 'let' at line 1:0\\n")
    sys.exit(1)
if "deep" in src:
    time.sleep(0.4)
    raise RecursionError("maximum recursion depth exceeded in evaluator")
print("ok:", len(tokens), "tokens")
'''


def test_parallel_curve_is_in_rank_order(tmp_path):
    project = tmp_path / "toy"
    shutil.copytree(TOY, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    (project / "parser.py").write_text(SLOW_CRASH_PARSER)
    cfg = load_config(project / "spreadex.yaml")

    r = Campaign(cfg, log=lambda *_: None).run(jobs=4)
    assert r.executed == 60 and r.verdicts.get("crash") == 5

    with CorpusStore(cfg.state_dir) as store:
        rows = store.conn.execute(
            "SELECT rank, verdict, signature FROM executions WHERE run_id=? ORDER BY rank",
            (r.run_id,)).fetchall()
        stored = store.budget_curve(r.run_id)
    by_rank = rank_curve(row["signature"] if row["verdict"] == "crash" else None for row in rows)

    assert [row["rank"] for row in rows] == list(range(60))
    assert r.budget_curve == by_rank == stored
    first_crash = min(row["rank"] for row in rows if row["verdict"] == "crash")
    assert next(e for e, s in r.budget_curve if s) == first_crash + 1

    manifest = json.loads((r.run_dir / "manifest.json").read_text())
    assert [tuple(p) for p in manifest["results"]["budget_curve"]] == by_rank


def test_rank_curve_counts_distinct_signatures():
    assert rank_curve([None, "a", None, "a", "b"]) == [(1, 0), (2, 1), (3, 1), (4, 1), (5, 2)]
