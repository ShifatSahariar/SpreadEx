"""The guided demo's workspace: a managed project with its own Workbench, separate from the user's."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

import pytest
import yaml

from spreadex import demo
from spreadex.api import registry
from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.config import Config, load_config
from spreadex.core.lock import RunLock
from spreadex.corpus.store import CorpusStore

TOKEN = "origin-token"


@pytest.fixture
def origin(tmp_path):
    """The user's own Workbench, on a folder with nothing in it yet."""
    project = tmp_path / "mine"
    project.mkdir()
    (project / "notes.txt").write_text("mine")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = Config.unconfigured(project)
    httpd.spreadex_token = TOKEN
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = False
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", project
    httpd.shutdown()
    httpd.server_close()


def call(url, body=None, token=TOKEN):
    req = Request(url, data=None if body is None else json.dumps(body).encode(),
                  method="GET" if body is None else "POST")
    req.add_header("X-SpreadEx-Token", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def _token(url):
    return parse_qs(urlparse(url).query)["token"][0]


def test_the_demo_config_asks_the_user_for_nothing(tmp_path):
    cfg = load_config(demo.materialize(tmp_path / "d") / "spreadex.yaml")
    assert cfg.targets and cfg.targets[0].command
    assert cfg.raw["grammar"]["source"] and cfg.raw["corpus"]["path"]
    assert cfg.generators and cfg.oracle.get("type") and cfg.oracle.get("rejection_patterns")
    assert cfg.budget.generation_s and cfg.budget.execution_s and cfg.seed is not None


def test_open_writes_the_managed_demo_and_serves_it_separately(origin):
    base, project = origin
    status, st = call(base + "/api/demo")
    assert status == 200 and st["exists"] is False and st["is_demo"] is False

    status, out = call(base + "/api/demo/open", {})
    assert status == 200 and out["ok"], out
    root = demo.demo_root()
    assert out["root"] == str(root) and (root / "spreadex.yaml").is_file()
    assert out["url"].endswith("&tour=1") and urlparse(out["url"]).port != urlparse(base).port

    # the demo Workbench is its own project, marked as the demo, with the way back
    demo_base = out["url"].split("/?")[0]
    _, p = call(demo_base + "/api/project", token=_token(out["url"]))
    assert p["demo"] is True and p["root"] == str(root) and p["return_url"].startswith("http://127.0.0.1:")
    _, mine = call(base + "/api/project")
    assert mine["demo"] is False and mine["return_url"] is None

    # the user's folder is exactly as it was
    assert sorted(x.name for x in project.iterdir()) == ["notes.txt"]

    # listed, and marked as living inside the Workbench that opened it
    entry = next(e for e in registry.live_servers() if e["root"] == str(root))
    assert entry["embedded_in"] == str(project.resolve())
    with pytest.raises(registry.Embedded):
        registry.stop(root)


def test_a_second_open_reuses_the_same_demo_workbench(origin):
    base, _ = origin
    _, first = call(base + "/api/demo/open", {})
    _, second = call(base + "/api/demo/open", {})
    assert first["url"] == second["url"]
    _, st = call(base + "/api/demo")
    assert st["exists"] and st["live"]


def test_start_fresh_wipes_the_demo_history_but_not_while_it_runs(origin):
    base, _ = origin
    call(base + "/api/demo/open", {})
    root = demo.demo_root()
    with CorpusStore(root / ".spreadex") as s:
        s.start_run("old", config_hash="x")
        s.finish_run("old")
    (root / "calc.py").write_text("# edited\n")
    _, st = call(base + "/api/demo")
    assert st["has_runs"] is True

    lock = RunLock(root / ".spreadex")
    lock.acquire(origin="ui")
    try:
        status, out = call(base + "/api/demo/open", {"reset": True})
        assert status == 409 and out["ok"] is False
    finally:
        lock.release()

    status, out = call(base + "/api/demo/open", {"reset": True})
    assert status == 200 and out["ok"]
    _, st = call(base + "/api/demo")
    assert st["has_runs"] is False
    assert "edited" not in (root / "calc.py").read_text()


def test_prepare_generators_falls_back_to_the_seeds_when_install_fails(tmp_path, monkeypatch):
    from spreadex.generators import GeneratorError, GeneratorManager

    def boom(self, *a, **k):
        raise GeneratorError("no network")
    monkeypatch.setattr(GeneratorManager, "ensure", boom)
    cfg = load_config(demo.materialize(tmp_path / "d") / "spreadex.yaml")
    lines = []
    demo.prepare_generators(cfg, log=lines.append)
    assert cfg.generators == [] and any("seed inputs instead" in l for l in lines)


def test_the_guide_shows_two_real_rules_of_the_demo_grammar():
    rules = demo.grammar_excerpt(demo.source_dir() / "calc.bnf")
    text = (demo.source_dir() / "calc.bnf").read_text()
    assert len(rules) == 2 and rules[0].startswith("<expr> ::=") and '"(" <expr> ")"' in rules[1]
    for r in rules:   # each alternative is verbatim from the file
        for alt in r.split("::=", 1)[1].split("|"):
            assert alt.strip() in text


def test_demo_status_carries_the_grammar_excerpt(origin):
    base, _ = origin
    call(base + "/api/demo/open", {})
    _, st = call(base + "/api/demo")
    assert st["grammar_rules"] == demo.grammar_excerpt(demo.demo_root() / "calc.bnf")
