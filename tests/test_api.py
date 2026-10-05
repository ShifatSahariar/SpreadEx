"""The local UI server.

A localhost bind is not an authentication boundary, so the security controls
are tested as carefully as the data.
"""

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from spreadex.api import data
from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A real campaign, served by a real server on an ephemeral port.

    Module-scoped: the campaign is the slow part and none of these tests change
    it, so running it once keeps the suite usable.
    """
    import shutil
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"
    project = tmp_path_factory.mktemp("ui") / "toy"
    # Never copy a .spreadex the developer happens to have lying around, or the
    # test sees their runs as well as its own.
    shutil.copytree(example, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    config = load_config(project / "spreadex.yaml")
    Campaign(config, log=lambda *_: None).run(jobs=4)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = "test-token-value"
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = False   # the default a user gets
    httpd.spreadex_jobs = JobRunner()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}", httpd.spreadex_token, config
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def read_only_server(served):
    """The same project, served with --read-only."""
    _, token, config = served
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = token
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = True
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", token
    httpd.shutdown()
    httpd.server_close()


def get(url, token=None, host=None):
    req = Request(url)
    if token:
        req.add_header("X-SpreadEx-Token", token)
    if host:
        req.add_header("Host", host)
    with urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read()) if "json" in r.headers.get("Content-Type", "") else r.read()


def status_of(url, token=None, host=None):
    try:
        return get(url, token, host)[0]
    except HTTPError as exc:
        return exc.code


# ------------------------------------------------------------------ security

def test_api_requires_a_token(served):
    base, token, _ = served
    assert status_of(f"{base}/api/runs") == 401
    assert status_of(f"{base}/api/runs", token="wrong") == 401
    assert status_of(f"{base}/api/runs", token=token) == 200


def test_token_is_accepted_in_the_query_for_the_first_load(served):
    base, token, _ = served
    assert status_of(f"{base}/api/runs?token={token}") == 200


def test_the_static_shell_needs_no_token(served):
    """The token is stripped from the address bar after first load, so gating
    the shell would make a plain refresh impossible. It carries no data."""
    base, _, _ = served
    assert status_of(f"{base}/") == 200


def test_a_non_local_host_header_is_refused(served):
    """This, not Origin checking, is what defeats DNS rebinding -- and it must
    hold even for a request carrying a valid token."""
    base, token, _ = served
    assert status_of(f"{base}/api/runs", token=token, host="evil.example.com") == 403
    assert status_of(f"{base}/", host="evil.example.com") == 403


def test_loopback_host_variants_are_allowed(served):
    base, token, _ = served
    port = base.rsplit(":", 1)[1]
    for host in (f"localhost:{port}", f"127.0.0.1:{port}"):
        assert status_of(f"{base}/api/runs", token=token, host=host) == 200


def test_static_paths_cannot_escape_the_static_directory(served):
    base, _, _ = served
    assert status_of(f"{base}/static/../../../../etc/passwd") == 404


def test_blob_hash_is_validated(served):
    base, token, _ = served
    assert status_of(f"{base}/api/input?hash=../../etc/passwd", token=token) == 400


def test_security_headers_are_present(served):
    base, _, _ = served
    with urlopen(Request(f"{base}/"), timeout=10) as r:
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp
        assert "connect-src 'self'" in csp          # nothing may leave the machine
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("Cache-Control") == "no-store"


def test_unknown_routes_404(served):
    base, token, _ = served
    assert status_of(f"{base}/api/nope", token=token) == 404


# ---------------------------------------------------------------------- data

def test_runs_and_detail(served):
    base, token, _ = served
    _, payload = get(f"{base}/api/runs", token)
    assert len(payload["runs"]) == 1
    run_id = payload["runs"][0]["run_id"]

    _, detail = get(f"{base}/api/runs/{run_id}", token)
    assert detail["verdicts"]["ok"] == 40
    assert detail["verdicts"]["expected_rejection"] == 15
    assert detail["verdicts"]["crash"] == 5
    assert len(detail["signatures"]) == 1
    assert detail["signatures"][0]["stderr"], "a signature needs its stderr for triage"
    assert detail["budget_curve"] and detail["random_curve"]


def test_missing_run_is_404(served):
    base, token, _ = served
    assert status_of(f"{base}/api/runs/nope", token=token) == 404


def test_input_can_be_fetched_for_triage(served):
    base, token, _ = served
    _, payload = get(f"{base}/api/runs", token)
    run_id = payload["runs"][0]["run_id"]
    _, detail = get(f"{base}/api/runs/{run_id}", token)
    blob = detail["signatures"][0]["example"]

    _, body = get(f"{base}/api/input?hash={blob}", token)
    assert "deep" in body["text"], "should return the input that triggers the signature"
    assert body["generators"]


def test_random_baseline_is_a_fair_comparison(served):
    """Same executed inputs, reshuffled -- so the curve isolates the ORDERING,
    which is the only thing prioritization controls."""
    base, token, _ = served
    _, payload = get(f"{base}/api/runs", token)
    _, detail = get(f"{base}/api/runs/{payload['runs'][0]['run_id']}", token)

    actual, random_curve = detail["budget_curve"], detail["random_curve"]
    assert len(actual) == len(random_curve) == detail["executed"]
    # Both end at the same total: the same failures are found either way.
    assert actual[-1][1] == pytest.approx(random_curve[-1][1], abs=0.01)
    # Monotone: a cumulative count cannot decrease.
    assert all(b[1] >= a[1] for a, b in zip(random_curve, random_curve[1:]))


def test_grammar_report_when_none_configured(served):
    base, token, _ = served
    _, payload = get(f"{base}/api/grammar", token)
    assert payload["configured"] is False      # toy-parser is corpus-only


def test_project_summary(served):
    base, token, _ = served
    _, payload = get(f"{base}/api/project", token)
    assert payload["targets"] and payload["signal"] == "cc"


def test_project_summary_exposes_read_only_state(read_only_server):
    base, token = read_only_server
    _, payload = get(f"{base}/api/project", token)
    assert payload["read_only"] is True


def test_a_stray_browser_path_redirects_to_the_page(served):
    """Someone typing a path into the address bar gets the UI, not raw JSON.
    `/spreadex` in particular was a route in the older research webapp."""
    from urllib.request import build_opener, HTTPRedirectHandler

    base, _, _ = served

    class Capture(HTTPRedirectHandler):
        location = None

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            Capture.location = newurl
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    with build_opener(Capture).open(f"{base}/spreadex", timeout=10) as r:
        assert r.status == 200
    assert Capture.location.endswith("/")


def test_unknown_api_routes_still_404_rather_than_redirect(served):
    """An API typo must fail loudly; only browser paths are forgiven."""
    base, token, _ = served
    assert status_of(f"{base}/api/nonsense", token=token) == 404


# ------------------------------------------------------------ write access

def post(url, body, token=None, host=None, as_query=False):
    import urllib.parse

    target = f"{url}?token={urllib.parse.quote(token)}" if as_query and token else url
    req = Request(target, data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    if token and not as_query:
        req.add_header("X-SpreadEx-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except HTTPError as exc:
        # Keep the body: for a refusal the message is the actionable part, and
        # a test that only sees the status cannot tell a helpful 403 from a
        # blank one.
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": raw.decode("utf-8", "replace")}


def test_writes_reject_a_token_supplied_only_in_the_query(served):
    """A mutating route takes its token from a HEADER only. A cross-origin form
    can POST but cannot set a custom header without a CORS preflight that this
    server never answers -- that is what keeps a hostile page out."""
    base, token, _ = served
    assert post(f"{base}/api/config", {"yaml": "x"}, token=token, as_query=True)[0] == 401
    assert post(f"{base}/api/config", {"yaml": "x"}, token=token)[0] == 200


def test_writes_reject_a_non_local_host(served):
    base, token, _ = served
    assert post(f"{base}/api/config", {"yaml": "x"}, token=token,
                host="evil.example.com")[0] == 403


def test_writes_require_a_token_at_all(served):
    base, _, _ = served
    assert post(f"{base}/api/config", {"yaml": "x"})[0] == 401


def test_config_is_validated_before_it_is_written(served):
    """A broken configuration must never land on top of a working one."""
    base, token, config = served
    original = (config.project_root / "spreadex.yaml").read_text()

    status, body = post(f"{base}/api/config", {"yaml": "sut: {}\n", "write": True}, token=token)
    assert status == 200 and body["ok"] is False
    assert body["errors"]
    assert (config.project_root / "spreadex.yaml").read_text() == original


def test_a_dry_run_does_not_write(served):
    base, token, config = served
    original = (config.project_root / "spreadex.yaml").read_text()
    good = 'sut:\n  command: ["echo", "{input}"]\ncorpus: {path: ./seeds}\ngenerators: []\n'

    status, body = post(f"{base}/api/config", {"yaml": good}, token=token)
    assert status == 200 and body["ok"] is True and "preview" in body
    assert (config.project_root / "spreadex.yaml").read_text() == original

    status, body = post(f"{base}/api/config", {"yaml": good, "write": True}, token=token)
    assert body["ok"] is True and "written" in body
    assert (config.project_root / "spreadex.yaml").read_text() == good


def test_read_only_mode_refuses_every_write(read_only_server):
    base, token = read_only_server
    assert post(f"{base}/api/config", {"yaml": "x"}, token=token)[0] == 403
    assert post(f"{base}/api/run", {}, token=token)[0] == 403
    # Reading still works: --read-only restricts changes, not visibility.
    assert status_of(f"{base}/api/runs", token=token) == 200


def test_generator_and_file_listings(served):
    base, token, _ = served
    _, gens = get(f"{base}/api/generators", token)
    ids = {g["id"] for g in gens["generators"]}
    assert {"fuzzingbook", "fandango", "isla", "grammarinator"} <= ids
    assert all("installed" in g and "dialect" in g for g in gens["generators"])

    _, files = get(f"{base}/api/files", token)
    assert "grammars" in files


def test_activity_is_idle_before_anything_runs(served):
    base, token, _ = served
    _, body = get(f"{base}/api/activity", token)
    assert body.get("idle") or body.get("done")


# --------------------------------------------------------- assistance routes

def test_providers_are_listed(experimental_server):
    base, token, _ = experimental_server
    _, body = get(f"{base}/api/providers", token)
    assert {p["id"] for p in body["providers"]} == {"openai", "anthropic", "ollama"}


def test_assist_without_a_key_fails_clearly(experimental_server, monkeypatch):
    base, token, _ = experimental_server
    status, body = post(f"{base}/api/assist",
                        {"task": "infer", "provider": "openai", "description": "a tiny language"},
                        token=token)
    assert status == 200 and body["ok"] is False
    assert "API key" in body["error"]


def test_assist_rejects_an_unknown_task(experimental_server):
    base, token, _ = experimental_server
    _, body = post(f"{base}/api/assist", {"task": "take-over-the-world"}, token=token)
    assert body["ok"] is False and "unknown task" in body["error"]


def test_saving_a_grammar_cannot_escape_the_project(served):
    base, token, config = served
    _, body = post(f"{base}/api/grammar/save",
                   {"path": "../../escaped.bnf", "text": '<start> ::= "x"'}, token=token)
    assert body["ok"] is False and "inside this project" in body["error"]
    assert not (config.project_root.parent.parent / "escaped.bnf").exists()


def test_saving_refuses_a_grammar_the_validator_rejects(served):
    """Accepting a proposal has to mean it passed."""
    base, token, _ = served
    _, body = post(f"{base}/api/grammar/save",
                   {"path": "bad.bnf", "text": "<start> ::= <nope>"}, token=token)
    assert body["ok"] is False and "refusing to save" in body["error"]


def test_saving_a_valid_grammar_works(served):
    base, token, config = served
    _, body = post(f"{base}/api/grammar/save",
                   {"path": "generated.bnf", "text": '<start> ::= "hello"'}, token=token)
    assert body["ok"] is True
    assert (config.project_root / "generated.bnf").read_text() == '<start> ::= "hello"'


def test_assistance_routes_are_refused_in_read_only_mode(read_only_server):
    base, token = read_only_server
    assert post(f"{base}/api/assist", {"task": "infer"}, token=token)[0] == 403
    assert post(f"{base}/api/grammar/save", {"path": "x.bnf", "text": "y"}, token=token)[0] == 403


# ------------------------------------------------------------ stable URL

def test_the_token_survives_restarts(tmp_path):
    """A fresh token per launch meant the URL changed every time and nothing
    could be bookmarked. It is now per project and persistent."""
    import shutil
    from pathlib import Path

    from spreadex.api.server import project_token
    from spreadex.core.config import load_config

    example = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"
    project = tmp_path / "toy"
    shutil.copytree(example, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    config = load_config(project / "spreadex.yaml")

    first = project_token(config)
    assert first and project_token(config) == first, "the URL must not move between launches"

    rotated = project_token(config, rotate=True)
    assert rotated != first
    assert project_token(config) == rotated


def test_the_token_file_is_owner_only_and_git_ignored(tmp_path):
    import shutil
    import stat
    from pathlib import Path

    from spreadex.api.server import TOKEN_FILE, project_token
    from spreadex.core.config import load_config

    example = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"
    project = tmp_path / "toy"
    shutil.copytree(example, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    config = load_config(project / "spreadex.yaml")
    project_token(config)

    path = config.state_dir / TOKEN_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Whichever code creates .spreadex/ first must leave the .gitignore behind.
    assert (config.state_dir / ".gitignore").read_text().strip().endswith("*")


def test_each_project_gets_its_own_token(tmp_path):
    """One project's saved link must not open another's corpus."""
    import shutil
    from pathlib import Path

    from spreadex.api.server import project_token
    from spreadex.core.config import load_config

    example = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"
    tokens = []
    for name in ("a", "b"):
        project = tmp_path / name
        shutil.copytree(example, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
        tokens.append(project_token(load_config(project / "spreadex.yaml")))
    assert tokens[0] != tokens[1]


# --------------------------------------------------- unconfigured projects

@pytest.fixture
def experimental_server(served):
    """The same project, served with the grammar assistant switched on.

    Its own server rather than a flag flipped on the shared one: the whole
    point of the other tests is that the assistant is absent unless asked for,
    and a fixture that mutated the shared server could not promise that.
    """
    _, _, config = served

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = "test-token-value"
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = True
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd.spreadex_token, config
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def empty_project(tmp_path):
    """A directory with no spreadex.yaml, served as the wizard would be."""
    from spreadex.api.server import project_token
    from spreadex.core.config import Config

    root = tmp_path / "fresh"
    root.mkdir()
    config = Config.unconfigured(root)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = project_token(config)
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd.spreadex_token, root, httpd
    httpd.shutdown()
    httpd.server_close()


def test_the_ui_serves_a_directory_with_no_config(empty_project):
    """The wizard's whole job is to write spreadex.yaml, so it has to be
    reachable before one exists."""
    base, token, _, _ = empty_project
    assert status_of(f"{base}/", token=token) == 200

    _, project = get(f"{base}/api/project", token)
    assert project["configured"] is False
    assert project["targets"] == [] and project["generators"] == []

    _, runs = get(f"{base}/api/runs", token)
    assert runs["runs"] == []

    _, conf = get(f"{base}/api/config", token)
    assert conf["exists"] is False


def test_an_unconfigured_project_is_left_untouched(empty_project):
    """Open the UI in the wrong directory, close it, leave no trace."""
    base, token, root, _ = empty_project
    get(f"{base}/api/project", token)
    get(f"{base}/api/runs", token)
    get(f"{base}/api/config", token)
    assert list(root.iterdir()) == [], f"the UI littered: {list(root.iterdir())}"


def test_corpus_routes_404_before_there_is_a_corpus(empty_project):
    base, token, _, _ = empty_project
    assert status_of(f"{base}/api/runs/anything", token=token) == 404
    assert status_of(f"{base}/api/input?hash=deadbeef", token=token) == 404


def test_saving_a_config_is_adopted_without_a_restart(empty_project):
    base, token, root, httpd = empty_project
    (root / "seeds").mkdir()
    (root / "seeds" / "a.txt").write_text("hello")
    yaml_text = (
        'sut:\n  command: ["echo", "{input}"]\n  timeout: 5s\n'
        "oracle: {type: crash}\ngenerators: []\ncorpus: {path: ./seeds}\n"
    )
    status, body = post(f"{base}/api/config", {"yaml": yaml_text, "write": True}, token=token)
    assert status == 200 and body["ok"] is True

    _, project = get(f"{base}/api/project", token)
    assert project["configured"] is True
    assert [t["name"] for t in project["targets"]] == ["sut"]
    assert httpd.spreadex_config.configured is True


def test_the_token_is_persisted_once_a_project_exists(empty_project):
    """Held in memory while there is nowhere to put it; written the moment
    there is."""
    from spreadex.api.server import TOKEN_FILE

    base, token, root, _ = empty_project
    assert not (root / ".spreadex" / TOKEN_FILE).exists()

    post(f"{base}/api/config",
         {"yaml": 'sut:\n  command: ["echo"]\ngenerators: []\ncorpus: {path: .}\n',
          "write": True}, token=token)
    saved = (root / ".spreadex" / TOKEN_FILE).read_text().strip()
    assert saved == token, "the link the user already has must keep working"


def test_opening_the_ui_does_not_create_state_for_a_configured_project(served):
    """A configured project that has never run should not get a .spreadex just
    from someone looking at it."""
    import shutil
    from pathlib import Path

    from spreadex.core.config import load_config

    example = Path(__file__).resolve().parents[1] / "examples" / "toy-parser"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "toy"
        shutil.copytree(example, project, ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
        config = load_config(project / "spreadex.yaml")

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        httpd.spreadex_config = config
        httpd.spreadex_token = "t"
        httpd.spreadex_verbose = False
        httpd.spreadex_read_only = False
        httpd.spreadex_jobs = JobRunner()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            _, runs = get(f"{url}/api/runs", "t")
            assert runs["runs"] == []
            assert not config.state_dir.exists(), "merely looking should not create a corpus"
        finally:
            httpd.shutdown()
            httpd.server_close()


# ------------------------------------------------- testing-strategy config

@pytest.mark.parametrize(
    "oracle_yaml, expected",
    [
        # Crashes and hangs only -- the floor, always on.
        ("oracle: {type: crash}\n", ("crash", [], [])),
        # "This system reports invalid input itself".
        ('oracle:\n  type: crash\n  rejection_patterns: ["SyntaxError", "^js: "]\n',
         ("crash", ["SyntaxError", "^js: "], [])),
        # Advanced: a message that always outranks a rejection rule.
        ('oracle:\n  type: crash\n  rejection_patterns: ["error"]\n'
         '  crash_patterns: ["java.lang.NullPointerException"]\n',
         ("crash", ["error"], ["java.lang.NullPointerException"])),
    ],
)
def test_the_strategy_step_writes_a_config_the_engine_accepts(empty_project, oracle_yaml, expected):
    """The checkboxes only compose things the oracle already understands, so
    what the wizard writes has to survive the real loader."""
    base, token, root, httpd = empty_project
    yaml_text = ('sut:\n  command: ["echo", "{input}"]\n  timeout: 5s\n'
                 + oracle_yaml + "generators: []\ncorpus: {path: .}\n")
    status, body = post(f"{base}/api/config", {"yaml": yaml_text, "write": True}, token=token)
    assert status == 200 and body["ok"] is True

    from spreadex.exec.oracle import make_oracle

    raw = httpd.spreadex_config.raw["oracle"]
    kind, rejection, crash = expected
    assert raw.get("type") == kind
    assert raw.get("rejection_patterns", []) == rejection
    assert raw.get("crash_patterns", []) == crash
    make_oracle(raw)  # must not raise


def test_expected_exit_codes_survive_the_wizard(empty_project):
    """Emitted by buildYaml now; the engine has always read it."""
    base, token, _, httpd = empty_project
    yaml_text = ('sut:\n  command: ["echo"]\noracle:\n  type: crash\n'
                 "  expected_exit_codes: [0, 1, 2]\ngenerators: []\ncorpus: {path: .}\n")
    status, _ = post(f"{base}/api/config", {"yaml": yaml_text, "write": True}, token=token)
    assert status == 200
    assert httpd.spreadex_config.raw["oracle"]["expected_exit_codes"] == [0, 1, 2]


def test_differential_needs_two_targets(empty_project):
    """The UI disables the checkbox with one target; the loader is what actually
    enforces it, so a hand-edited file is caught too."""
    base, token, _, httpd = empty_project
    status, body = post(
        f"{base}/api/config",
        {"yaml": 'sut:\n  command: ["echo"]\noracle: {type: differential}\n'
                 "generators: []\ncorpus: {path: .}\n", "write": True}, token=token)
    # Validation failures are a result, not a transport error: the wizard
    # renders them beside the field.
    assert status == 200 and body["ok"] is False
    assert "two entries" in " ".join(body["errors"])
    assert httpd.spreadex_config.configured is False, "a rejected config is not adopted"


# ------------------------------------------------ verifying a test command

def test_probe_runs_the_command_and_reports_what_happened(empty_project):
    base, token, _, _ = empty_project
    status, body = post(f"{base}/api/probe",
                        {"command": ["cat", "{input}"], "sample": "hello\n"}, token=token)
    assert status == 200 and body["ok"] is True
    assert body["exit_code"] == 0 and body["timed_out"] is False
    assert body["stdout"].strip() == "hello"
    assert body["substituted"] is True


def test_probe_appends_the_path_when_input_is_not_mentioned(empty_project):
    """Same rule the campaign uses, so what the user verifies is what runs."""
    base, token, _, _ = empty_project
    _, body = post(f"{base}/api/probe", {"command": ["cat"], "sample": "x\n"}, token=token)
    assert body["ok"] is True and body["substituted"] is False
    assert body["command"][-1].endswith("sample.txt")


def test_probe_explains_a_command_that_does_not_exist(empty_project):
    """The typo the user is here to catch."""
    base, token, _, _ = empty_project
    _, body = post(f"{base}/api/probe",
                   {"command": ["./definitely-not-here", "{input}"]}, token=token)
    assert body["ok"] is False
    assert "not found" in body["error"]


def test_probe_reports_a_rejection_without_calling_it_a_failure(empty_project):
    """A parser refusing bad input is working. The probe must not say 'crash'."""
    base, token, _, _ = empty_project
    _, body = post(f"{base}/api/probe",
                   {"command": ["sh", "-c", "echo 'SyntaxError' >&2; exit 1"]}, token=token)
    assert body["ok"] is True, "the probe ran; the SUT's verdict is not the probe's"
    assert body["exit_code"] == 1
    assert "SyntaxError" in body["stderr"]
    assert "crash" not in json.dumps(body).lower()


def test_probe_needs_a_command(empty_project):
    base, token, _, _ = empty_project
    _, body = post(f"{base}/api/probe", {"command": "   "}, token=token)
    assert body["ok"] is False and "command" in body["error"]


def test_probe_is_refused_in_read_only_mode(empty_project):
    """It executes what the browser typed, so --read-only must stop it."""
    _, _, _, httpd = empty_project
    httpd.spreadex_read_only = True
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, _ = post(f"{base}/api/probe", {"command": ["echo"]},
                         token=httpd.spreadex_token)
        assert status == 403
    finally:
        httpd.spreadex_read_only = False


# ------------------------------------------- the assistant is off by default

def test_the_assistant_is_refused_unless_asked_for(served):
    """Hiding the button is not an off switch. The route has to refuse, so a
    default install cannot be made to contact a model provider at all."""
    base, token, _ = served
    status, body = post(f"{base}/api/assist",
                        {"task": "infer", "description": "anything"}, token=token)
    assert status == 403
    assert "--experimental" in json.dumps(body)


def test_providers_are_empty_unless_asked_for(served):
    """The UI asks this to decide whether to offer the feature at all."""
    base, token, _ = served
    _, body = get(f"{base}/api/providers", token)
    assert body["providers"] == [] and body["experimental"] is False


def test_the_project_payload_says_whether_it_is_on(served, experimental_server):
    _, project = get(f"{served[0]}/api/project", served[1])
    assert project["experimental"] is False
    _, project = get(f"{experimental_server[0]}/api/project", experimental_server[1])
    assert project["experimental"] is True
