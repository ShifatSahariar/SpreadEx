"""Talk to a language model over plain HTTP.

No vendor SDK: three providers, one small adapter each, using urllib. That
keeps `pip install spreadex` free of a dependency the tool only needs when a
user opts into assistance, and it keeps the surface small enough to audit.

Nothing here decides anything. A model's output is a PROPOSAL that
spreadex.llm.assist puts through the ordinary grammar validator before a user
is ever shown it as usable.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

TIMEOUT = 120


class LLMError(Exception):
    """A problem reaching or understanding a model, phrased for the user."""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    env_var: str | None
    default_model: str
    local: bool
    note: str = ""


PROVIDERS = {
    "openai": Provider("openai", "OpenAI", "OPENAI_API_KEY", "gpt-4o-mini", False),
    "anthropic": Provider("anthropic", "Anthropic", "ANTHROPIC_API_KEY",
                          "claude-sonnet-5", False),
    "ollama": Provider("ollama", "Ollama (local)", None, "llama3.1", True,
                       "Runs on this machine; nothing leaves it."),
}


def available() -> list[dict]:
    """Which providers look usable right now, for the UI to offer."""
    out = []
    for p in PROVIDERS.values():
        has_key = bool(p.env_var and os.environ.get(p.env_var))
        out.append({
            "id": p.id, "label": p.label, "local": p.local, "note": p.note,
            "default_model": p.default_model,
            "env_var": p.env_var,
            "key_in_env": has_key,
            "needs_key": not p.local and not has_key,
        })
    return out


def complete(provider: str, system: str, user: str, *,
             api_key: str | None = None, model: str | None = None,
             base_url: str | None = None, max_tokens: int = 2500) -> str:
    """One completion. Raises LLMError with something the user can act on."""
    try:
        spec = PROVIDERS[provider]
    except KeyError:
        raise LLMError(f"Unknown provider {provider!r}. "
                       f"Known: {', '.join(PROVIDERS)}") from None

    model = model or spec.default_model
    key = api_key or (os.environ.get(spec.env_var) if spec.env_var else None)
    if not spec.local and not key:
        raise LLMError(
            f"{spec.label} needs an API key.\n"
            f"  Set {spec.env_var}, or paste a key into the assistant. "
            f"A pasted key is held for this session only and never written to disk."
        )

    if provider == "openai":
        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"model": model, "max_tokens": max_tokens, "temperature": 0.1,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        pick = lambda d: d["choices"][0]["message"]["content"]
    elif provider == "anthropic":
        url = (base_url or "https://api.anthropic.com/v1") + "/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        payload = {"model": model, "max_tokens": max_tokens, "temperature": 0.1,
                   "system": system, "messages": [{"role": "user", "content": user}]}
        pick = lambda d: "".join(b.get("text", "") for b in d["content"])
    else:  # ollama
        url = (base_url or "http://127.0.0.1:11434") + "/api/chat"
        headers = {"Content-Type": "application/json"}
        payload = {"model": model, "stream": False,
                   "options": {"temperature": 0.1},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        pick = lambda d: d["message"]["content"]

    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise LLMError(f"{spec.label} returned {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        if spec.local:
            raise LLMError(
                f"Could not reach Ollama at {base_url or 'http://127.0.0.1:11434'}.\n"
                f"  Fix: start it with `ollama serve`, and pull the model with "
                f"`ollama pull {model}`."
            ) from None
        raise LLMError(f"Could not reach {spec.label}: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise LLMError(f"{spec.label} timed out after {TIMEOUT}s: {exc}") from None

    try:
        text = pick(data)
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"{spec.label} returned an unexpected response shape") from None
    if not text or not text.strip():
        raise LLMError(f"{spec.label} returned nothing")
    return text


def extract_code_block(text: str) -> str:
    """The fenced block if there is one, otherwise the whole reply."""
    if "```" not in text:
        return text.strip()
    parts = text.split("```")
    if len(parts) < 2:
        return text.strip()
    block = parts[1]
    first, _, rest = block.partition("\n")
    # Drop a language tag such as ```bnf
    if first.strip() and " " not in first.strip():
        block = rest
    return block.strip()
