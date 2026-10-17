"""The session-only API key over HTTP: settable with the token, never returned, clearable."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.config import load_config
from spreadex.llm import settings

KEY = "sk-test-NEVER-ECHO-0123456789"


@pytest.fixture()
def server(tmp_path):
    (tmp_path / "spreadex.yaml").write_text(
        "sut:\n  command: [x, '{input}']\ncorpus:\n  path: ./seeds\ngenerators: []\n"
        "llm: {provider: openai, model: gpt-4.1-mini}\n")
    (tmp_path / "seeds").mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = load_config(tmp_path / "spreadex.yaml")
    httpd.spreadex_token = "tok"
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = False
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    settings.clear_session_key()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    settings.clear_session_key()
    httpd.shutdown()
    httpd.server_close()


def _post(url, body, token="tok"):
    req = Request(url, data=json.dumps(body).encode(), method="POST",
                  headers={"Content-Type": "application/json", **({"X-SpreadEx-Token": token} if token else {})})
    with urlopen(req, timeout=10) as r:
        return r.read().decode()


def _get(url):
    with urlopen(Request(url + "?token=tok"), timeout=10) as r:
        return r.read().decode()


def test_the_key_is_set_for_the_session_and_never_returned(server, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert json.loads(_get(server + "/api/llm/status"))["key_source"] == "none"
    reply = _post(server + "/api/llm/key", {"key": KEY})
    assert KEY not in reply and json.loads(reply)["key_source"] == "session"
    status = _get(server + "/api/llm/status")
    assert KEY not in status and json.loads(status)["key_source"] == "session"
    assert settings.session_key() == KEY


def test_setting_the_key_needs_the_token(server):
    with pytest.raises(HTTPError) as exc:
        _post(server + "/api/llm/key", {"key": KEY}, token=None)
    assert exc.value.code == 401
    assert settings.session_key() is None


def test_the_key_can_be_cleared(server, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _post(server + "/api/llm/key", {"key": KEY})
    reply = json.loads(_post(server + "/api/llm/key/clear", {}))
    assert reply["key_source"] == "none" and settings.session_key() is None


def test_an_empty_key_is_refused(server):
    assert json.loads(_post(server + "/api/llm/key", {"key": "  "}))["ok"] is False
