"""The Workbench's run lifecycle routes: active, cancel, delete, re-run, and the 409s."""
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.core.lock import RunLock

TOKEN = "lifecycle-token"


@pytest.fixture
def served(tmp_path):
    (tmp_path / "sut.py").write_text("import sys\nsys.exit(0)\n")
    (tmp_path / "seeds").mkdir()
    for i in range(3):
        (tmp_path / "seeds" / f"s{i}").write_text(f"input {i}")
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": [sys.executable, "sut.py"], "cwd": ".", "timeout": "5s"},
        "oracle": {"type": "crash", "expected_exit_codes": [0]},
        "generators": [], "corpus": {"path": "seeds"},
        "budget": {"generation": "5s", "execution": "60s"}}))
    config = load_config(tmp_path / "spreadex.yaml")
    rid = Campaign(config, log=lambda *_: None).run().run_id
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = TOKEN
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = False
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", config, rid, httpd
    httpd.shutdown()
    httpd.server_close()


def call(url, body=None):
    req = Request(url, data=None if body is None else json.dumps(body).encode(),
                  method="GET" if body is None else "POST")
    req.add_header("X-SpreadEx-Token", TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def _wait_idle(httpd):
    for _ in range(200):
        if not httpd.spreadex_jobs.busy:
            return
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_active_reflects_the_os_lock_including_cli_runs(served):
    base, config, rid, _ = served
    assert call(base + "/api/active") == (200, {"active": False})
    lock = RunLock(config.state_dir)
    lock.acquire(origin="cli")
    lock.set_run("from-cli")
    try:
        status, body = call(base + "/api/active")
        assert body["active"] and body["run_id"] == "from-cli" and body["origin"] == "cli"
        # a second campaign is refused with 409, naming the active one
        status, body = call(base + "/api/run", {})
        assert status == 409 and body["active_run"] == "from-cli"
        status, body = call(base + "/api/runs/from-cli/cancel", {})
        assert status == 200 and body["cancelling"]
        # deleting anything while a campaign is mid-flight is a 409 for the running one
        status, _ = call(base + "/api/runs/from-cli/delete", {})
        assert status == 409
    finally:
        lock.release()


def test_cancel_of_a_run_that_is_not_running_is_refused(served):
    base, _, rid, _ = served
    status, body = call(base + f"/api/runs/{rid}/cancel", {})
    assert status == 200 and body["ok"] is False


def test_runs_list_carries_status_origin_and_size(served):
    base, _, rid, _ = served
    _, body = call(base + "/api/runs")
    r = body["runs"][0]
    assert r["run_id"] == rid and r["status"] == "finished" and r["origin"] == "cli"
    assert r["size_bytes"] > 0


def test_rerun_uses_the_recorded_config_then_delete_removes_it(served):
    base, config, rid, httpd = served
    # change the saved config: the re-run must still use what the run recorded
    raw = yaml.safe_load((config.project_root / "spreadex.yaml").read_text())
    raw["corpus"]["path"] = "nowhere"
    (config.project_root / "spreadex.yaml").write_text(yaml.safe_dump(raw))
    status, body = call(base + f"/api/runs/{rid}/rerun", {})
    assert status == 200 and body["ok"], body
    _wait_idle(httpd)
    job = httpd.spreadex_jobs.current
    assert job.ok, job.lines
    new = job.result["run_id"]
    assert new != rid and job.result["executed"] == 3
    assert not list(config.project_root.glob(".spreadex-rerun-*"))
    _, body = call(base + "/api/runs")
    assert {r["run_id"]: r["origin"] for r in body["runs"]}[new] == "ui"

    status, body = call(base + f"/api/runs/{new}/delete", {})
    assert status == 200 and body["ok"]
    _, body = call(base + "/api/runs")
    assert [r["run_id"] for r in body["runs"]] == [rid]
    status, body = call(base + "/api/runs/missing/delete", {})
    assert body["ok"] is False
