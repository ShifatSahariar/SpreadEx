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
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}", httpd.spreadex_token, config
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
