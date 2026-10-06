"""Run lifecycle: one campaign per project, cancel, status, and safe deletion."""
import json
import sys

import pytest
import yaml

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.core.lock import RunInProgress, RunLock, active_run, cancel_file
from spreadex.corpus.store import CorpusStore

SUT = 'import sys\nt = open(sys.argv[1]).read()\nsys.exit(1 if "boom" in t else 0)\n'


def _project(root, seeds):
    (root / "sut.py").write_text(SUT)
    (root / "seeds").mkdir(exist_ok=True)
    for name, text in seeds.items():
        (root / "seeds" / name).write_text(text)
    (root / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": [sys.executable, "sut.py"], "cwd": ".", "timeout": "5s"},
        "oracle": {"type": "crash", "expected_exit_codes": [0]},
        "generators": [], "corpus": {"path": "seeds"},
        "budget": {"generation": "5s", "execution": "60s"}}))
    return load_config(root / "spreadex.yaml")


def _quiet(cfg, **kw):
    return Campaign(cfg, log=lambda *_: None, **kw)


def _status(cfg, rid):
    with CorpusStore(cfg.state_dir) as s:
        return s.conn.execute("SELECT status, origin FROM runs WHERE run_id=?", (rid,)).fetchone()


def test_a_second_campaign_is_refused_while_one_holds_the_lock(tmp_path):
    cfg = _project(tmp_path, {"a": "fine"})
    held = RunLock(cfg.state_dir)
    held.acquire(origin="ui")
    held.set_run("R-1")
    try:
        assert active_run(cfg.state_dir)["run_id"] == "R-1"
        with pytest.raises(RunInProgress) as e:
            _quiet(cfg).run()
        assert e.value.info["origin"] == "ui"
    finally:
        held.release()
    assert active_run(cfg.state_dir) is None


def test_a_leftover_lock_file_without_an_os_lock_blocks_nothing(tmp_path):
    cfg = _project(tmp_path, {"a": "fine"})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (cfg.state_dir / "run.lock").write_text(json.dumps({"run_id": "ghost", "pid": 999999}))
    assert active_run(cfg.state_dir) is None
    rid = _quiet(cfg).run().run_id
    assert _status(cfg, rid)["status"] == "finished"
    assert active_run(cfg.state_dir) is None


def test_a_run_that_died_unfinished_is_marked_aborted_by_the_next_one(tmp_path):
    cfg = _project(tmp_path, {"a": "fine"})
    with CorpusStore(cfg.state_dir) as s:
        s.start_run("dead", config_hash="x")
    _quiet(cfg).run()
    assert _status(cfg, "dead")["status"] == "aborted"


def test_cancel_by_event_stops_and_records_cancelled(tmp_path):
    cfg = _project(tmp_path, {f"a{i}": f"fine {i}" for i in range(5)})
    c = _quiet(cfg, origin="ui")
    c.stop_event.set()
    r = c.run()
    assert r.executed == 0
    row = _status(cfg, r.run_id)
    assert row["status"] == "cancelled" and row["origin"] == "ui"


def test_cancel_by_file_reaches_a_run_in_another_process(tmp_path):
    cfg = _project(tmp_path, {f"a{i}": f"fine {i}" for i in range(5)})
    c = Campaign(cfg)

    def log(line):
        if line.startswith("Executing"):
            cancel_file(cfg.state_dir, c.run_id).write_text("")
    c.log = log
    r = c.run()
    assert r.executed == 0 and _status(cfg, r.run_id)["status"] == "cancelled"


def test_delete_reclaims_only_what_no_other_run_uses(tmp_path):
    cfg = _project(tmp_path, {"shared": "fine shared", "boom": "boom one"})
    first = _quiet(cfg).run().run_id
    (tmp_path / "seeds" / "own").write_text("fine only second")
    second = _quiet(cfg).run().run_id
    with CorpusStore(cfg.state_dir) as s:
        h = {r["blob_hash"]: r for r in s.conn.execute("SELECT * FROM inputs")}
        own = next(k for k in h if s.get_blob(k) == b"fine only second")
        shared = next(k for k in h if s.get_blob(k) == b"fine shared")
        assert s.run_blob_bytes(second) == len(b"fine only second")
        out = s.delete_run(second)
        assert out["inputs_removed"] == 1
        assert not s.blob_path(own).exists() and s.blob_path(shared).exists()
        assert not s.run_dir(second).exists() and s.run_dir(first).exists()
        assert s.conn.execute("SELECT COUNT(*) c FROM executions WHERE run_id=?",
                              (second,)).fetchone()["c"] == 0
        # the crash both runs saw now belongs to the first run alone
        f = s.conn.execute("SELECT * FROM failures").fetchone()
        assert f["first_seen_run"] == first and f["last_seen_run"] == first
        assert f["occurrences"] == 1
        s.delete_run(first)
        assert s.conn.execute("SELECT COUNT(*) c FROM failures").fetchone()["c"] == 0
        assert s.conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"] == 0
        with pytest.raises(KeyError):
            s.delete_run(first)


def test_an_old_store_gets_status_backfilled(tmp_path):
    import sqlite3
    cfg = _project(tmp_path, {"a": "fine"})
    with CorpusStore(cfg.state_dir) as s:
        s.start_run("old-done", config_hash="x")
        s.finish_run("old-done")
        s.start_run("old-open", config_hash="x")
    con = sqlite3.connect(cfg.state_dir / "corpus.db")
    con.execute("ALTER TABLE runs DROP COLUMN status")
    con.commit()
    con.close()
    with CorpusStore(cfg.state_dir) as s:
        st = {r["run_id"]: r["status"] for r in s.conn.execute("SELECT run_id, status FROM runs")}
    assert st == {"old-done": "finished", "old-open": "aborted"}
