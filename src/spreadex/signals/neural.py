"""UniXcoder embeddings, as the ICST 2026 study computed them.

Mirrors research/EMBEDDINGS/VECTOR_MODELS/uni_x_coder_Embedding.py: RobertaTokenizer and
RobertaModel from microsoft/unixcoder-base, truncation at 512 tokens, and the [CLS] vector
(last_hidden_state[:, 0, :]) with no pooling or normalization.

Two deliberate differences, both for reproducibility rather than speed:

* The model is pinned to a commit, not "main", so a re-run months later loads the same weights.
  The weights are read from the repository's safetensors conversion (refs/pr/8), which holds the
  same tensors as the original pytorch_model.bin (checked: max abs difference 0.0) and loads
  without unpickling a downloaded file.
* Inputs are embedded one at a time, without padding. The research code batched 50 with padding,
  which moves a vector by ~1e-5 depending on its batch companions; one at a time, an input's
  vector depends only on the input, so a cached vector equals a recomputed one exactly.

torch and transformers come from the `neural` extra. Anything that stops the model loading is
raised as EmbeddingUnavailable, which the caller turns into a fallback and a caveat.
"""

from __future__ import annotations

import threading
from typing import Callable, Sequence

import numpy as np

MODEL = "microsoft/unixcoder-base"
#: config.json, vocab.json, merges.txt and the tokenizer settings.
CONFIG_REVISION = "5604afdc964f6c53782a6813140ade5216b99006"
#: model.safetensors (refs/pr/8 on the Hub).
WEIGHTS_REVISION = "558aa506226b13a7e83f66cb38c53e61b9603eac"
WEIGHTS_FILE = "model.safetensors"
MAX_TOKENS = 512
DIM = 768
#: What a first use downloads into the Hugging Face cache, for the UI and the log.
DOWNLOAD_MB = 506
#: Cache key: changes whenever anything that changes a vector changes.
CACHE_ID = f"unixcoder@{WEIGHTS_REVISION[:12]}:cls:{MAX_TOKENS}"

_LOADED: dict[str, tuple] = {}
_LOCK = threading.Lock()


class EmbeddingUnavailable(RuntimeError):
    """The backend cannot run here; the message says why and how to fix it."""


def dependencies_missing() -> str | None:
    """The pip command that would make this backend importable, or None if it already is."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        import safetensors  # noqa: F401
    except ImportError:
        return "pip install 'spreadex[neural]'"
    return None


def is_downloaded() -> bool:
    """Whether the pinned weights are already in the Hugging Face cache (no network needed)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    path = try_to_load_from_cache(MODEL, WEIGHTS_FILE, revision=WEIGHTS_REVISION)
    return isinstance(path, str)


def _load(device: str, log: Callable[[str], None]):
    missing = dependencies_missing()
    if missing:
        raise EmbeddingUnavailable(f"UniXcoder needs torch and transformers. Fix: {missing}")
    key = device
    if key in _LOADED:
        return _LOADED[key]
    with _LOCK:
        if key in _LOADED:
            return _LOADED[key]
        import torch
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from transformers import RobertaConfig, RobertaModel, RobertaTokenizer

        if not is_downloaded():
            log(f"  downloading UniXcoder ({DOWNLOAD_MB} MB, first use only) into the Hugging Face cache")
        try:
            tokenizer = RobertaTokenizer.from_pretrained(MODEL, revision=CONFIG_REVISION)
            config = RobertaConfig.from_pretrained(MODEL, revision=CONFIG_REVISION)
            weights = hf_hub_download(MODEL, WEIGHTS_FILE, revision=WEIGHTS_REVISION)
        except Exception as exc:  # offline, proxy, disk full: all mean "not here, not now"
            raise EmbeddingUnavailable(
                f"UniXcoder could not be downloaded ({type(exc).__name__}: {str(exc).splitlines()[0][:160]}). "
                f"Fix: connect once so the model can be cached, or choose TF-IDF."
            ) from exc
        model = RobertaModel(config)
        state = load_file(weights)
        result = model.load_state_dict({k.removeprefix("roberta."): v for k, v in state.items()},
                                       strict=False)
        if result.missing_keys:
            raise EmbeddingUnavailable(
                f"UniXcoder's weights are incomplete ({len(result.missing_keys)} tensors missing). "
                f"Fix: delete the cached model and let it download again.")
        try:
            model = model.to(torch.device(device)).eval()
        except (RuntimeError, AssertionError) as exc:
            raise EmbeddingUnavailable(f"UniXcoder cannot use device {device!r}: {exc}") from exc
        _LOADED[key] = (tokenizer, model, device)
        return _LOADED[key]


def embed_unixcoder(texts: Sequence[str], device: str = "cpu",
                    log: Callable[[str], None] = lambda _m: None) -> np.ndarray:
    """One 768-d [CLS] vector per text, in order."""
    import torch

    tokenizer, model, device = _load(device, log)
    out = np.empty((len(texts), DIM), dtype=np.float32)
    step = max(1, len(texts) // 10)
    with torch.inference_mode():
        for i, text in enumerate(texts):
            enc = tokenizer([text if text.strip() else " "], truncation=True, max_length=MAX_TOKENS,
                            return_tensors="pt").to(device)
            out[i] = model(**enc).last_hidden_state[0, 0, :].float().cpu().numpy()
            if len(texts) >= 200 and (i + 1) % step == 0:
                log(f"  embedded {i + 1:,} of {len(texts):,} inputs with UniXcoder")
    return out
