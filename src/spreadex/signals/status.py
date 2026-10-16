"""Can each embedding backend run here, and what would it cost? For `doctor` and the Workbench.

Cheap and side-effect free: it checks imports, the Hugging Face cache and an environment
variable. It never downloads, loads a model, or calls a service.
"""

from __future__ import annotations

from .base import _FALLBACK_CHAIN, _LABELS, EMBEDDING_MODELS, default_embedding


def _unixcoder() -> dict:
    from . import neural

    missing = neural.dependencies_missing()
    downloaded = not missing and neural.is_downloaded()
    if missing:
        status, fix = "torch and transformers are not installed", missing
    elif downloaded:
        status, fix = "ready, model cached on this machine", ""
    else:
        status, fix = f"ready; the first campaign downloads the model ({neural.DOWNLOAD_MB} MB, once)", ""
    return {"id": "unixcoder", "label": _LABELS["unixcoder"], "local": True,
            "ready": not missing, "downloaded": downloaded, "download_mb": neural.DOWNLOAD_MB,
            "dim": neural.DIM, "status": status, "fix": fix,
            "model": f"{neural.MODEL}@{neural.WEIGHTS_REVISION[:12]}"}


def _openai() -> dict:
    from . import remote

    has_key = remote.key_present()
    return {"id": "openai", "label": _LABELS["openai"], "local": False, "ready": has_key,
            "dim": remote.DIM, "env_var": remote.ENV_VAR, "key_in_env": has_key,
            "status": f"{remote.ENV_VAR} is set; inputs are sent to OpenAI" if has_key
                      else f"{remote.ENV_VAR} is not set",
            "fix": "" if has_key else f"export {remote.ENV_VAR}=... before starting SpreadEx",
            "model": remote.MODEL}


def _tfidf() -> dict:
    return {"id": "tfidf", "label": _LABELS["tfidf"], "local": True, "ready": True, "dim": None,
            "status": "ready, no download or key needed", "fix": "", "model": "char 2-4-grams"}


def embedding_status(selected: str | None = None) -> dict:
    selected = (selected or default_embedding()).lower()
    if selected not in EMBEDDING_MODELS:
        selected = default_embedding()
    backends = [_unixcoder(), _openai(), _tfidf()]
    ready = {b["id"]: b["ready"] for b in backends}
    fallback_to = next((m for m in _FALLBACK_CHAIN[selected] if ready[m]), "tfidf")
    return {"selected": selected, "default": default_embedding(), "backends": backends,
            "fallback_to": None if ready[selected] else fallback_to}
