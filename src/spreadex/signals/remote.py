"""OpenAI text-embedding-3-small, the model the ICST 2026 prioritization experiments used.

Opt-in only. It sends every generated input to OpenAI, needs the user's own key in
OPENAI_API_KEY (never read from spreadex.yaml, never written anywhere), and costs money. The
request mirrors research/EMBEDDINGS/VECTOR_MODELS/OpenAI_Embedding.py: the raw input text, model
text-embedding-3-small, the returned vector unchanged.

Vectors are cached by the caller, which also makes a re-run reproducible: the service does not
promise bit-identical vectors for the same text across calls.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Sequence

import numpy as np

from .neural import EmbeddingUnavailable

MODEL = "text-embedding-3-small"
DIM = 1536
ENV_VAR = "OPENAI_API_KEY"
URL = "https://api.openai.com/v1/embeddings"
CACHE_ID = f"openai:{MODEL}"
BATCH = 100
#: The model reads at most 8,191 tokens. Counting tokens needs tiktoken; characters are a safe
#: proxy (code runs at ~3-4 characters per token), so longer inputs are cut, as the research
#: code's API call would have refused them.
MAX_CHARS = 20_000
RETRIES = 4
TIMEOUT = 60


def key_present() -> bool:
    return bool(os.environ.get(ENV_VAR))


def _post(payload: dict, key: str) -> dict:
    request = urllib.request.Request(
        URL, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def embed_openai(texts: Sequence[str], log: Callable[[str], None] = lambda _m: None,
                 post: Callable[[dict, str], dict] = _post) -> np.ndarray:
    key = os.environ.get(ENV_VAR)
    if not key:
        raise EmbeddingUnavailable(
            f"OpenAI embeddings need an API key. Fix: set {ENV_VAR} in the environment that "
            f"starts SpreadEx, or choose UniXcoder, which runs on this machine.")
    out = np.empty((len(texts), DIM), dtype=np.float32)
    for start in range(0, len(texts), BATCH):
        batch = [(t if t.strip() else " ")[:MAX_CHARS] for t in texts[start:start + BATCH]]
        for attempt in range(RETRIES):
            try:
                data = post({"model": MODEL, "input": batch}, key)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise EmbeddingUnavailable(
                        f"OpenAI refused the key in {ENV_VAR} ({exc.code}). Fix: check the key.") from None
                if exc.code not in (429, 500, 502, 503, 504) or attempt == RETRIES - 1:
                    detail = exc.read().decode(errors="replace")[:200]
                    raise EmbeddingUnavailable(f"OpenAI returned {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == RETRIES - 1:
                    raise EmbeddingUnavailable(f"Could not reach OpenAI: {exc}") from None
            time.sleep(2 ** attempt)
        try:
            rows = sorted(data["data"], key=lambda d: d["index"])
            out[start:start + len(batch)] = np.asarray([r["embedding"] for r in rows], dtype=np.float32)
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailable(f"OpenAI returned an unexpected response ({exc}).") from None
        if len(texts) > BATCH:
            log(f"  embedded {min(start + BATCH, len(texts)):,} of {len(texts):,} inputs with OpenAI")
    return out
