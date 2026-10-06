"""The Results workspace's data: every number comes from what the run recorded."""
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from spreadex.api import data, setup
from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.corpus.store import CorpusStore

SUT = '''import sys, time
t = open(sys.argv[1]).read()
if "hang" in t:
    time.sleep(5)
if "boom" in t:
    sys.stderr.write("Caught an Exception: boom in tokenizer\\n")
    sys.exit(1)
if "refuse" in t:
    sys.stderr.write("SyntaxError: nope\\n")
    sys.exit(3)
print("ok")
'''

INPUTS = {"a1": "fine 1", "a2": "fine 2", "a3": "fine 3", "a4": "fine 4",
          "r1": "refuse 1", "r2": "refuse 2", "r3": "refuse 3",
          "b1": "boom 1", "b2": "boom 22", "b3": "boom 333", "h1": "hang"}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("res")
    (root / "sut.py").write_text(SUT)
    (root / "seeds").mkdir()
    for name, text in INPUTS.items():
        (root / "seeds" / name).write_text(text)
    (root / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": [sys.executable, "sut.py"], "cwd": ".", "timeout": "1s"},
        "oracle": {"type": "crash", "expected_exit_codes": [0], "rejection_patterns": ["^SyntaxError"],
                   "crash_patterns": ["Caught an Exception"]},
        "generators": [], "corpus": {"path": "seeds"},
        "budget": {"generation": "5s", "execution": "60s"}}))
    cfg = load_config(root / "spreadex.yaml")
    result = Campaign(cfg, log=lambda *_: None).run(jobs=2)
    # attribute the inputs to two generators so per-generator figures have something to split
    with CorpusStore(cfg.state_dir) as store:
        hashes = [r["blob_hash"] for r in store.conn.execute("SELECT blob_hash FROM inputs ORDER BY blob_hash")]
        for i, h in enumerate(hashes):
            store.conn.execute("UPDATE inputs SET generator=? WHERE blob_hash=?", ("alpha" if i % 2 else "beta", h))
        store.conn.commit()
    return cfg, result.run_id


def test_the_overview_counts_match_what_ran(run):
    cfg, rid = run
    d = data.results_overview(cfg.state_dir, rid)
    assert d["executed"] == len(INPUTS) and d["complete"] is True and d["run_id"] == rid and "number" not in d
    v = d["verdicts"]
    assert v["ok"] == 4 and v["expected_rejection"] == 3 and v["crash"] == 3 and v["timeout"] == 1
    assert d["duration_s"] is not None and d["duration_s"] >= 0


def test_findings_group_by_signature_numbered_in_the_order_first_reached(run):
    cfg, rid = run
    f = data.results_overview(cfg.state_dir, rid)["findings"]
    assert [x["id"] for x in f] == [f"F-{i:03d}" for i in range(1, len(f) + 1)]
    kinds = {x["verdict"]: x for x in f}
    assert set(kinds) == {"crash", "timeout"}
    assert kinds["crash"]["count"] == 3 and kinds["timeout"]["count"] == 1
    positions = [x["position"] for x in f]
    assert positions == sorted(positions)


def test_the_per_generator_rows_add_up_to_the_whole(run):
    cfg, rid = run
    d = data.results_overview(cfg.state_dir, rid)
    gens = {g["name"]: g for g in d["by_generator"]}
    assert {"alpha", "beta"} <= set(gens)
    assert sum(g["executed"] for g in d["by_generator"]) == d["executed"]
    assert sum(g["verdicts"]["crash"] for g in d["by_generator"]) == d["verdicts"]["crash"]
    for g in d["by_generator"]:
        if g["executed"]:
            assert g["pass_rate"] == pytest.approx(g["verdicts"]["ok"] / g["executed"])
    assert sum(g["findings"] for g in d["by_generator"]) >= 1


def test_the_timeline_covers_every_execution_exactly_once(run):
    cfg, rid = run
    t = data.results_overview(cfg.state_dir, rid)["timeline"]
    assert sum(b["to"] - b["from"] + 1 for b in t) == len(INPUTS)
    assert all(t[i]["to"] + 1 == t[i + 1]["from"] for i in range(len(t) - 1))
    assert sum(b["crash"] for b in t) == 3 and sum(b["timeout"] for b in t) == 1


def test_prioritization_reports_when_findings_were_reached(run):
    cfg, rid = run
    p = data.results_overview(cfg.state_dir, rid)["prioritization"]
    assert p["executed"] == len(INPUTS) and p["findings"] == 2
    assert 1 <= p["first_at"] <= p["all_at"] <= len(INPUTS)
    assert p["by_half"] <= p["findings"]


def test_the_corpus_listing_filters_pages_and_searches(run):
    cfg, rid = run
    allp = data.run_inputs(cfg.state_dir, rid, limit=5)
    assert allp["total"] == len(INPUTS) and len(allp["items"]) == 5 and allp["facets"]["verdicts"]["crash"] == 3
    only = data.run_inputs(cfg.state_dir, rid, verdict="expected_rejection", limit=50)
    assert only["total"] == 3 and all(i["verdict"] == "expected_rejection" for i in only["items"])
    page2 = data.run_inputs(cfg.state_dir, rid, offset=5, limit=5)
    assert page2["items"][0]["rank"] > allp["items"][-1]["rank"]
    boom = data.run_inputs(cfg.state_dir, rid, q="BOOM", limit=50)
    assert boom["total"] == 3 and all("boom" in i["preview"] for i in boom["items"])
    byhash = data.run_inputs(cfg.state_dir, rid, q=boom["items"][0]["hash"][:10])
    assert byhash["total"] == 1
    gen = data.run_inputs(cfg.state_dir, rid, generator="alpha", limit=50)
    assert gen["total"] == allp["facets"]["generators"]["alpha"]
    assert all(i["finding"] for i in boom["items"]), "failing inputs name their finding"
    assert data.run_inputs(cfg.state_dir, "nope") is None


def test_the_listing_limits_are_clamped(run):
    cfg, rid = run
    assert data.run_inputs(cfg.state_dir, rid, limit=10_000)["limit"] == 100
    assert data.run_inputs(cfg.state_dir, rid, offset=-5)["offset"] == 0


def _crash(cfg, rid):
    f = data.results_overview(cfg.state_dir, rid)["findings"]
    return next(x for x in f if x["verdict"] == "crash")


def test_a_finding_explains_itself_with_the_input_stderr_and_evidence(run):
    cfg, rid = run
    c = _crash(cfg, rid)
    d = data.finding_detail(cfg.state_dir, rid, c["signature"])
    assert d["id"] == c["id"] and "boom" in d["input"] and "Caught an Exception" in d["stderr"]
    assert d["headline"].startswith("Caught an Exception") and d["count"] == 3 and d["similar_total"] == 2
    ev = {e["rule"]: e for e in d["evidence"]}
    assert ev["Crash pattern"]["status"] == "matched" and ev["Crash pattern"]["note"] == "Caught an Exception"
    assert ev["Timeout"]["status"] == "no" and ev["Expected rejection"]["status"] == "no"
    assert d["exit_code"] == 1 and d["number"] >= 1 and d["of"] == 2


def test_a_timeout_finding_says_so_in_its_evidence(run):
    cfg, rid = run
    f = next(x for x in data.results_overview(cfg.state_dir, rid)["findings"] if x["verdict"] == "timeout")
    ev = {e["rule"]: e for e in data.finding_detail(cfg.state_dir, rid, f["signature"])["evidence"]}
    assert ev["Timeout"]["status"] == "matched"


def test_an_unknown_signature_or_run_is_none(run):
    cfg, rid = run
    assert data.finding_detail(cfg.state_dir, rid, "deadbeef") is None
    assert data.finding_detail(cfg.state_dir, "nope", "x") is None


def test_the_evidence_is_the_engines_order_without_inventing_a_match():
    ev = data.classification_evidence({"crash_patterns": ["Boom"], "rejection_patterns": ["^Syntax"]},
                                      {"verdict": "crash", "detail": "exit 2"}, "something else")
    rules = [e["rule"] for e in ev]
    assert rules == ["Timeout", "Killed by a signal", "Crash pattern", "Expected rejection", "Unexpected non-zero exit"]
    assert next(e for e in ev if e["rule"] == "Crash pattern")["status"] == "no"
    sig = data.classification_evidence({}, {"verdict": "crash", "detail": "signal 11"}, "")
    assert next(e for e in sig if e["rule"] == "Killed by a signal")["status"] == "matched"
    assert not any(e["rule"] == "Unexpected non-zero exit" for e in sig)


# ----------------------------------------------------------------- replay

def test_replay_reproduces_a_crash(run):
    cfg, rid = run
    c = _crash(cfg, rid)
    r = setup.replay_input(cfg, rid, c["example"])
    assert r["ok"] and r["reproduced"] is True and r["replay"]["verdict"] == "crash" and r["original"]["verdict"] == "crash"
    assert "Caught an Exception" in r["replay"]["stderr"]


def test_replay_notices_when_the_bug_is_gone(run, tmp_path):
    cfg, rid = run
    c = _crash(cfg, rid)
    (cfg.project_root / "sut.py").write_text("print('fixed')\n")
    try:
        r = setup.replay_input(cfg, rid, c["example"])
    finally:
        (cfg.project_root / "sut.py").write_text(SUT)
    assert r["ok"] and r["reproduced"] is False and r["replay"]["verdict"] == "ok" and r["original"]["verdict"] == "crash"


def test_replay_refuses_what_it_should(run):
    cfg, rid = run
    assert not setup.replay_input(cfg, rid, "../etc")["ok"]
    assert not setup.replay_input(cfg, rid, "0" * 64)["ok"]
    assert not setup.replay_input(cfg, "nope", _crash(cfg, rid)["example"])["ok"]


def test_replay_writes_nothing_to_the_corpus(run):
    cfg, rid = run
    with CorpusStore(cfg.state_dir) as s:
        before = s.conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    setup.replay_input(cfg, rid, _crash(cfg, rid)["example"])
    with CorpusStore(cfg.state_dir) as s:
        assert s.conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == before


# ----------------------------------------------------------------- export

def test_export_carries_the_failing_inputs_and_the_config(run, tmp_path):
    from spreadex.core.export import ExportError, build_export
    cfg, rid = run
    rid2, out = build_export(cfg, rid, tmp_path / "x.zip")
    names = zipfile.ZipFile(out).namelist()
    assert rid2 == rid and "spreadex.yaml" in names and any(n.startswith("failing_inputs/") for n in names)
    assert any(n.endswith("manifest.json") for n in names)
    with pytest.raises(ExportError, match="no run"):
        build_export(cfg, "nope", tmp_path / "y.zip")


# ------------------------------------------------ the campaigns list and live progress

def test_the_campaigns_list_carries_what_each_row_shows(run):
    cfg, rid = run
    rows = data.list_runs(cfg.state_dir)
    r = next(x for x in rows if x["run_id"] == rid)
    assert r["run_id"] == rid and "number" not in r and r["complete"] is True and r["executed"] == len(INPUTS)
    assert r["findings"] == 2 and r["failures"] == 4          # 2 signatures over 4 failing inputs
    assert r["target"] and r["duration_s"] is not None and r["duration_s"] >= 0
    assert isinstance(r["generators"], list)


def test_the_list_numbers_runs_in_the_order_they_started(run, tmp_path):
    cfg, rid = run
    with CorpusStore(cfg.state_dir) as s:
        s.conn.execute("INSERT INTO runs(run_id, started_at, config_hash) VALUES (?,?,?)",
                       ("2099-01-01T00-00-00Z", "2099-01-01T00:00:00+00:00", "x"))
        s.conn.commit()
    try:
        rows = data.list_runs(cfg.state_dir)
        assert rows[0]["run_id"] == "2099-01-01T00-00-00Z" and rows[1]["run_id"] == rid
        assert rows[0]["complete"] is False and rows[0]["duration_s"] is None
    finally:
        with CorpusStore(cfg.state_dir) as s:
            s.conn.execute("DELETE FROM runs WHERE run_id=?", ("2099-01-01T00-00-00Z",))
            s.conn.commit()


def test_progress_of_a_finished_run_agrees_with_its_overview(run):
    cfg, rid = run
    p, d = data.run_progress(cfg.state_dir, rid), data.results_overview(cfg.state_dir, rid)
    assert p["complete"] is True and p["elapsed_s"] is None and p["executed"] == d["executed"]
    assert [f["id"] for f in p["findings"]] == [f["id"] for f in d["findings"]]
    assert [f["headline"] for f in p["findings"]] == [f["stderr_first"] for f in d["findings"]]
    assert p["latest"]["id"] == d["findings"][-1]["id"]


def test_progress_of_a_run_in_flight_reports_so_far_and_elapsed_time(run):
    cfg, rid = run
    with CorpusStore(cfg.state_dir) as s:
        h = [r["blob_hash"] for r in s.conn.execute("SELECT blob_hash FROM inputs LIMIT 3")]
        s.conn.execute("INSERT INTO runs(run_id, started_at, config_hash, exec_budget_s) VALUES (?,?,?,?)",
                       ("live-1", data._parse_time("2026-10-06T00:00:00+00:00").isoformat(), "x", 60))
        for i, (hh, v) in enumerate(zip(h, ("ok", "crash", "expected_rejection"))):
            s.conn.execute("INSERT INTO executions(run_id, blob_hash, rank, sut_id, verdict, signature, duration_ms) VALUES (?,?,?,?,?,?,?)",
                           ("live-1", hh, i, "sut", v, "sigX" if v == "crash" else None, 5.0))
        s.conn.commit()
    try:
        p = data.run_progress(cfg.state_dir, "live-1")
        assert p["complete"] is False and p["elapsed_s"] > 0 and p["executed"] == 3
        assert p["verdicts"] == {"ok": 1, "crash": 1, "expected_rejection": 1} and p["exec_budget_s"] == 60
        assert len(p["findings"]) == 1 and p["latest"]["verdict"] == "crash"
    finally:
        with CorpusStore(cfg.state_dir) as s:
            s.conn.execute("DELETE FROM executions WHERE run_id=?", ("live-1",))
            s.conn.execute("DELETE FROM runs WHERE run_id=?", ("live-1",))
            s.conn.commit()


def test_progress_of_an_unknown_run_is_none(run):
    cfg, _ = run
    assert data.run_progress(cfg.state_dir, "nope") is None


def test_results_are_committed_often_enough_for_a_live_view(tmp_path):
    """The live view reads the database while a campaign writes it, so what has executed so far must
    be visible well before the end. Checked from a second connection in the middle of a run."""
    import threading
    import time

    (tmp_path / "slow.py").write_text("import sys, time; time.sleep(0.15); print('ok')\n")
    (tmp_path / "seeds").mkdir()
    for i in range(40):
        (tmp_path / "seeds" / f"s{i}").write_text(f"input {i}")
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": [sys.executable, "slow.py"], "cwd": ".", "timeout": "5s"}, "oracle": {"type": "crash"},
        "generators": [], "corpus": {"path": "seeds"}, "budget": {"generation": "5s", "execution": "60s"}}))
    cfg = load_config(tmp_path / "spreadex.yaml")
    seen = []
    t = threading.Thread(target=lambda: Campaign(cfg, log=lambda *_: None).run(jobs=1))
    t.start()
    while t.is_alive():
        time.sleep(0.4)
        try:
            runs = data.list_runs(cfg.state_dir)
        except Exception:
            continue
        if runs and not runs[0]["complete"]:
            seen.append(runs[0]["executed"])
    t.join()
    assert any(0 < n < 40 for n in seen), f"never saw a partial count: {seen}"
