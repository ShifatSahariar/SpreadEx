"""Shared LLM settings for every LLM-based generator, and the session-only API key.

    llm:
      provider: openai          # openai | anthropic | ollama | vllm | custom
      model: gpt-4.1-mini       # required: never a hidden default
      base_url: ...             # only for custom (presets fill it in)
      api_key_env: OPENAI_API_KEY

One block, used by every generator whose catalog family is `llm-based`, so a developer states
the endpoint, model and key once. The interface is an OpenAI-compatible chat-completions
endpoint: base URL plus model are required, a key is optional for local servers, temperature is
passed where the provider allows it, token usage is recorded when the response reports it.

The key itself is never part of the configuration. It comes from the environment variable the
config names, or from a key pasted into the Workbench, which lives only in this process's memory
(`set_session_key`) and is gone on restart or `clear_session_key`.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from urllib.parse import urlparse

PRESETS: dict[str, dict] = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1",
               "api_key_env": "OPENAI_API_KEY", "local": False},
    "anthropic": {"label": "Anthropic (OpenAI-compatible endpoint)",
                  "base_url": "https://api.anthropic.com/v1/",
                  "api_key_env": "ANTHROPIC_API_KEY", "local": False},
    "ollama": {"label": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1",
               "api_key_env": None, "local": True},
    "vllm": {"label": "vLLM (local)", "base_url": "http://127.0.0.1:8000/v1",
             "api_key_env": None, "local": True},
    "custom": {"label": "Custom OpenAI-compatible endpoint", "base_url": None,
               "api_key_env": None, "local": False},
}
#: Shown in the Workbench as the pre-filled, editable model; never applied silently.
SUGGESTED_MODEL = "gpt-4.1-mini"

_SESSION_KEY: str | None = None
_LOCK = threading.Lock()


class LLMSettingsError(ValueError):
    """The settings cannot drive a generator; the message says what to fix."""


def set_session_key(key: str) -> None:
    global _SESSION_KEY
    key = (key or "").strip()
    if not key:
        raise LLMSettingsError("the key is empty")
    with _LOCK:
        _SESSION_KEY = key


def clear_session_key() -> None:
    global _SESSION_KEY
    with _LOCK:
        _SESSION_KEY = None


def session_key() -> str | None:
    return _SESSION_KEY


@dataclass(frozen=True)
class ResolvedLLM:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    key_source: str          # "session" | "env" | "none"
    local: bool

    @property
    def host(self) -> str:
        """For provenance: where requests went, never what authenticated them."""
        return urlparse(self.base_url).netloc or self.base_url

    def public(self) -> dict:
        return {"provider": self.provider, "model": self.model, "endpoint_host": self.host,
                "key_source": self.key_source, "local": self.local}


def normalize(raw: dict | None) -> dict:
    """Validate the `llm:` block as written. Only written keys are kept."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise LLMSettingsError("`llm` must be a mapping like `{provider: openai, model: gpt-4.1-mini}`.")
    if "api_key" in raw:
        raise LLMSettingsError("`llm` must not contain a key; name an environment variable in `api_key_env`.")
    unknown = set(raw) - {"provider", "model", "base_url", "api_key_env"}
    if unknown:
        raise LLMSettingsError(f"`llm` has unknown key(s): {', '.join(sorted(unknown))}.")
    provider = str(raw.get("provider") or "openai").lower()
    if provider not in PRESETS:
        raise LLMSettingsError(f"`llm.provider` must be one of {', '.join(PRESETS)}, not {provider!r}.")
    out = {"provider": provider}
    if raw.get("model") is not None:
        out["model"] = str(raw["model"]).strip()
    if raw.get("base_url"):
        url = str(raw["base_url"]).strip()
        if urlparse(url).scheme not in ("http", "https"):
            raise LLMSettingsError("`llm.base_url` must be an http(s) URL.")
        out["base_url"] = url
    if raw.get("api_key_env"):
        out["api_key_env"] = str(raw["api_key_env"]).strip()
    if provider == "custom" and "base_url" not in out:
        raise LLMSettingsError("`llm.provider: custom` needs `llm.base_url`.")
    return out


def resolve(llm: dict | None, *, require_key: bool = True) -> ResolvedLLM:
    """Everything a generator needs to call the model, or a fix the user can act on."""
    llm = normalize(llm)
    if not llm:
        raise LLMSettingsError(
            "LLM-based generators need LLM settings.\n"
            f"  Fix: add `llm: {{provider: openai, model: {SUGGESTED_MODEL}}}` to spreadex.yaml, "
            "or set them in the Workbench (step 3).")
    preset = PRESETS[llm["provider"]]
    model = llm.get("model") or ""
    if not model:
        raise LLMSettingsError(f"`llm.model` is not set. Fix: name a model, e.g. {SUGGESTED_MODEL}.")
    base_url = llm.get("base_url") or preset["base_url"]
    env_name = llm.get("api_key_env") or preset["api_key_env"]
    key, source = None, "none"
    if _SESSION_KEY:
        key, source = _SESSION_KEY, "session"
    elif env_name and os.environ.get(env_name):
        key, source = os.environ[env_name], "env"
    if key is None and require_key and not preset["local"]:
        raise LLMSettingsError(
            f"No API key for {preset['label']}.\n"
            f"  Fix: export {env_name or 'the key variable'} before starting SpreadEx, or paste a key "
            f"for this session in the Workbench (it is never saved).")
    return ResolvedLLM(provider=llm["provider"], model=model, base_url=base_url, api_key=key,
                       key_source=source, local=bool(preset["local"]))


def status(llm: dict | None) -> dict:
    """What the Workbench shows. Never contains the key."""
    try:
        cfg = normalize(llm)
    except LLMSettingsError as exc:
        return {"configured": False, "error": str(exc), "presets": _presets_public(),
                "suggested_model": SUGGESTED_MODEL, "key_source": "none"}
    provider = cfg.get("provider", "openai")
    preset = PRESETS[provider]
    env_name = cfg.get("api_key_env") or preset["api_key_env"]
    source = "session" if _SESSION_KEY else ("env" if env_name and os.environ.get(env_name) else "none")
    return {"configured": bool(cfg.get("model")), "settings": cfg, "presets": _presets_public(),
            "suggested_model": SUGGESTED_MODEL, "key_source": source, "key_env": env_name,
            "key_needed": not preset["local"]}


def _presets_public() -> dict:
    return {k: {kk: v[kk] for kk in ("label", "base_url", "api_key_env", "local")}
            for k, v in PRESETS.items()}


def subprocess_env(resolved: ResolvedLLM, base: dict | None = None) -> dict:
    """The environment for a generator process: an allow-list, plus the endpoint and key the
    OpenAI SDK reads. The key travels only here, never in argv, files or logs."""
    base = dict(os.environ if base is None else base)
    keep = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE", "JAVA_HOME",
            "SYSTEMROOT", "PYTHONHASHSEED", "SPREADEX_CACHE", "SPREADEX_HOME", "HF_HOME"}
    env = {k: v for k, v in base.items() if k in keep or k.startswith("SPREADEX_RUNTIME_")}
    env["PYTHONHASHSEED"] = "0"
    env["OPENAI_BASE_URL"] = resolved.base_url
    # The SDK refuses to start without a key; local servers ignore whatever it sends.
    env["OPENAI_API_KEY"] = resolved.api_key or "spreadex-local-no-key"
    return env
