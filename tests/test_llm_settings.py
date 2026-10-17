"""Shared LLM settings: validation, resolution, the session key, and what may leave the process."""

from __future__ import annotations

import pytest

from spreadex.core.config import ConfigError, load_config
from spreadex.llm import settings
from spreadex.llm.redact import redact, redact_obj


@pytest.fixture(autouse=True)
def _no_session_key():
    settings.clear_session_key()
    yield
    settings.clear_session_key()


def _write(tmp_path, block: str):
    (tmp_path / "spreadex.yaml").write_text(
        "sut:\n  command: [x, '{input}']\ncorpus:\n  path: ./seeds\ngenerators: []\n" + block)
    (tmp_path / "seeds").mkdir(exist_ok=True)
    return tmp_path / "spreadex.yaml"


def test_the_llm_block_keeps_only_what_was_written(tmp_path):
    cfg = load_config(_write(tmp_path, "llm: {provider: openai, model: gpt-4.1-mini}\n"))
    assert cfg.llm == {"provider": "openai", "model": "gpt-4.1-mini"}


@pytest.mark.parametrize("block, message", [
    ("llm: {provider: openai, model: m, api_key: sk-xyz}\n", "must not contain a key"),
    ("llm: {provider: nope, model: m}\n", "must be one of"),
    ("llm: {provider: custom, model: m}\n", "needs `llm.base_url`"),
    ("llm: {provider: custom, model: m, base_url: 'ftp://x'}\n", "http"),
    ("llm: {provider: openai, model: m, colour: blue}\n", "unknown key"),
])
def test_bad_llm_settings_are_refused(tmp_path, block, message):
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path, block))


def test_no_model_means_no_run_not_a_silent_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdef")
    with pytest.raises(settings.LLMSettingsError, match="llm.model"):
        settings.resolve({"provider": "openai"})
    with pytest.raises(settings.LLMSettingsError, match="need LLM settings"):
        settings.resolve({})


def test_presets_fill_endpoint_and_key_variable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdef")
    r = settings.resolve({"provider": "openai", "model": "gpt-4.1-mini"})
    assert r.base_url == "https://api.openai.com/v1" and r.key_source == "env"
    local = settings.resolve({"provider": "ollama", "model": "llama3.1"})
    assert local.local and local.api_key is None and local.host == "127.0.0.1:11434"


def test_a_remote_provider_without_a_key_says_how_to_supply_one(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(settings.LLMSettingsError, match="never saved"):
        settings.resolve({"provider": "openai", "model": "gpt-4.1-mini"})


def test_a_session_key_wins_over_the_environment_and_is_never_reported(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-0123456789abcdef")
    settings.set_session_key("sk-session-0123456789abcdef")
    r = settings.resolve({"provider": "openai", "model": "m"})
    assert r.api_key == "sk-session-0123456789abcdef" and r.key_source == "session"
    shown = repr(settings.status({"provider": "openai", "model": "m"})) + repr(r.public())
    assert "sk-session" not in shown and "sk-env" not in shown
    settings.clear_session_key()
    assert settings.resolve({"provider": "openai", "model": "m"}).key_source == "env"


def test_the_generator_environment_is_an_allow_list(monkeypatch):
    r = settings.ResolvedLLM("openai", "m", "https://api.openai.com/v1", "sk-x-0123456789abcdef",
                             "session", False)
    env = settings.subprocess_env(r, base={"PATH": "/bin", "HOME": "/h", "AWS_SECRET_ACCESS_KEY": "a",
                                           "GITHUB_TOKEN": "g", "SPREADEX_RUNTIME_RHINO": "/r"})
    assert env["OPENAI_API_KEY"] == "sk-x-0123456789abcdef"
    assert env["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert "AWS_SECRET_ACCESS_KEY" not in env and "GITHUB_TOKEN" not in env
    assert env["PATH"] == "/bin" and env["SPREADEX_RUNTIME_RHINO"] == "/r"


def test_redaction_scrubs_known_keys_and_key_shaped_strings(monkeypatch):
    settings.set_session_key("my-session-secret-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret-value")
    text = "failed: my-session-secret-value / anthropic-secret-value / sk-proj-ABCDEFGHIJKLMNOPQRST"
    out = redact(text)
    assert "secret-value" not in out and "sk-proj-" not in out and out.count("[redacted]") == 3
    assert redact_obj({"a": [text]}) == {"a": [out]}
