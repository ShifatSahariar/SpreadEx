"""A spreadex.yaml edited on disk while the Workbench is open is what the Workbench then shows.

Before, the server kept the configuration it started with: the page showed the old values and a
launch from it would have written them back over the user's edit.
"""
import json
import os
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.config import load_config

TOKEN = "edit-test-token"


@pytest.fixture
def served(tmp_path):
    (tmp_path / "spreadex.yaml").write_text(
        'sut: {command: [python3, v.py, "{input}"], timeout: 5s}\noracle: {type: crash}\n'
        "generators: []\ncorpus: {path: seeds}\n")
    (tmp_path / "seeds").mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = load_config(tmp_path / "spreadex.yaml")
    httpd.spreadex_token = TOKEN
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = False
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()
    httpd.server_close()


def get(base, route):
    with urlopen(Request(base + route, headers={"X-SpreadEx-Token": TOKEN}), timeout=10) as r:
        return json.loads(r.read())


def parsed(base):
    return get(base, "/api/config")["parsed"]


def post(base, route, body):
    req = Request(base + route, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", "X-SpreadEx-Token": TOKEN})
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _touch_later(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def test_an_edit_on_disk_is_adopted(served):
    base, project = served
    assert parsed(base)["sut"]["timeout"] == "5s"
    cfg = project / "spreadex.yaml"
    cfg.write_text(cfg.read_text().replace("timeout: 5s", "timeout: 7s"))
    _touch_later(cfg)
    assert parsed(base)["sut"]["timeout"] == "7s"


def test_an_edit_that_does_not_parse_is_not_a_configured_project(served):
    """The last good values stay on view, but nothing treats them as a reviewed setup, and a
    launch re-reads the file and refuses."""
    base, project = served
    assert get(base, "/api/project")["configured"] is True
    cfg = project / "spreadex.yaml"
    cfg.write_text("sut: [unclosed\n")
    _touch_later(cfg)
    assert parsed(base)["sut"]["timeout"] == "5s"
    info = get(base, "/api/project")
    assert info["configured"] is False and info["config_error"]
    assert get(base, "/api/config")["error"]
    started = post(base, "/api/run", {"jobs": 1})
    assert started["ok"] is False


def test_a_deleted_config_makes_the_project_unconfigured_and_cannot_launch(served):
    base, project = served
    assert get(base, "/api/project")["configured"] is True
    (project / "spreadex.yaml").unlink()
    assert get(base, "/api/project")["configured"] is False
    assert parsed(base) in ({}, None) and get(base, "/api/config")["exists"] is False
    started = post(base, "/api/run", {"jobs": 1})
    assert started["ok"] is False and "spreadex.yaml" in started["error"]


def test_a_fixed_config_is_adopted_again(served):
    base, project = served
    cfg = project / "spreadex.yaml"
    good = cfg.read_text()
    cfg.write_text("sut: [unclosed\n")
    _touch_later(cfg)
    assert get(base, "/api/project")["configured"] is False
    cfg.write_text(good.replace("timeout: 5s", "timeout: 9s"))
    _touch_later(cfg)
    assert get(base, "/api/project")["configured"] is True and parsed(base)["sut"]["timeout"] == "9s"
