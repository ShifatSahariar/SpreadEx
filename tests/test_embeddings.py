"""The embedding choice: default, validation, fallback, cache, OpenAI request shape, status.

No test here downloads a model or calls a service. One test runs the real UniXcoder model, and
only when it is already installed and cached on the machine.
"""

from __future__ import annotations

import io
import json
import urllib.error

import numpy as np
import pytest

from spreadex.core.config import ConfigError, load_config
from spreadex.signals import base, neural, remote
from spreadex.signals.base import ClusterCoverageSignal, Item, embed_pool
from spreadex.signals.cache import EmbeddingCache
from spreadex.signals.neural import EmbeddingUnavailable
from spreadex.signals.status import embedding_status

TEXTS = ["1 + 2", "3 * (4 - 5)", "x % 0", "((7))", "8 / 2 + 1", "9 - - 9"]


def _write(tmp_path, embedding_block: str = ""):
    (tmp_path / "spreadex.yaml").write_text(
        "sut:\n  command: [python3, x.py, '{input}']\ncorpus:\n  path: ./seeds\ngenerators: []\n"
        + embedding_block)
    (tmp_path / "seeds").mkdir()
    return tmp_path / "spreadex.yaml"


# ------------------------------------------------------------------ config

def test_unixcoder_is_the_product_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SPREADEX_DEFAULT_EMBEDDING")
    assert load_config(_write(tmp_path)).embedding == {"model": "unixcoder"}


def test_an_explicit_model_wins_over_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("SPREADEX_DEFAULT_EMBEDDING")
    cfg = load_config(_write(tmp_path, "embedding:\n  model: tfidf\n"))
    assert cfg.embedding == {"model": "tfidf"}


@pytest.mark.parametrize("block, message", [
    ("embedding:\n  model: word2vec\n", "must be one of"),
    ("embedding:\n  model: qwen3\n", "not available in this version"),
    ("embedding:\n  model: unixcoder\n  fallback: openai\n", "fallback"),
    ("embedding:\n  model: unixcoder\n  device: tpu\n", "device"),
    ("embedding:\n  model: unixcoder\n  colour: blue\n", "unknown key"),
])
def test_bad_embedding_settings_are_refused(tmp_path, block, message):
    with pytest.raises(ConfigError, match=message):
        load_config(_write(tmp_path, block))


def test_only_written_keys_enter_the_config(tmp_path):
    cfg = load_config(_write(tmp_path, "embedding:\n  model: openai\n  fallback: none\n"))
    assert cfg.embedding == {"model": "openai", "fallback": "none"}


# ---------------------------------------------------------------- fallback

def _unavailable(*_a, **_k):
    raise EmbeddingUnavailable("not installed here")


def test_unixcoder_falls_back_to_tfidf_and_says_so(monkeypatch):
    monkeypatch.setattr(neural, "_load", _unavailable)
    logs = []
    X, info = embed_pool(TEXTS, "unixcoder", log=logs.append)
    assert info.requested == "unixcoder" and info.used == "tfidf"
    assert "not installed here" in info.fallback_reason
    assert X.shape[0] == len(TEXTS)
    assert any("trying tfidf" in line for line in logs)


def test_openai_falls_back_to_unixcoder_first(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(neural, "_load", lambda *a, **k: None)
    monkeypatch.setattr(neural, "embed_unixcoder",
                        lambda ts, device="cpu", log=None: np.ones((len(ts), neural.DIM), np.float32))
    _, info = embed_pool(TEXTS, "openai")
    assert info.used == "unixcoder" and "OPENAI_API_KEY" in info.fallback_reason


def test_fallback_none_stops_the_campaign(monkeypatch):
    monkeypatch.setattr(neural, "_load", _unavailable)
    with pytest.raises(RuntimeError, match="fallback is `none`"):
        embed_pool(TEXTS, "unixcoder", fallback=False)


def test_a_fallback_becomes_a_caveat_on_the_ordering(monkeypatch):
    monkeypatch.setattr(neural, "_load", _unavailable)
    items = [Item(blob_hash=str(i), text=t, generator="g") for i, t in enumerate(TEXTS)]
    ordering = ClusterCoverageSignal(embedding_model="unixcoder", random_state=1).rank(items)
    assert ordering.embedding["used"] == "tfidf"
    assert any("instead of UniXcoder" in c for c in ordering.caveats)
    assert sorted(ordering.order) == list(range(len(TEXTS)))


def test_tfidf_requested_is_not_a_fallback():
    items = [Item(blob_hash=str(i), text=t, generator="g") for i, t in enumerate(TEXTS)]
    ordering = ClusterCoverageSignal(embedding_model="tfidf", random_state=1).rank(items)
    assert ordering.embedding["used"] == "tfidf" and not ordering.caveats


# ------------------------------------------------------------------- cache

def test_cache_computes_each_text_once_and_returns_identical_vectors(tmp_path):
    calls = []

    def compute(ts):
        calls.append(list(ts))
        return np.asarray([[len(t), t.count("1"), 0.5] for t in ts], dtype=np.float32)

    cache = EmbeddingCache(tmp_path / "e.sqlite")
    first, n1 = cache.embed("b@1", TEXTS + [TEXTS[0]], compute)
    second, n2 = cache.embed("b@1", list(reversed(TEXTS)), compute)
    assert (n1, n2) == (len(TEXTS), 0)
    assert calls == [TEXTS]                     # the duplicate was computed once
    assert np.array_equal(second, first[:len(TEXTS)][::-1])
    _, n3 = cache.embed("b@2", TEXTS, compute)  # another backend is a miss, not a stale hit
    assert n3 == len(TEXTS)


# ------------------------------------------------------------------ openai

def test_openai_request_matches_the_research_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = []

    def post(payload, key):
        seen.append((payload, key))
        return {"data": [{"index": i, "embedding": [float(i)] * remote.DIM}
                         for i in reversed(range(len(payload["input"])))]}

    X = remote.embed_openai(["a", "", "c"], post=post)
    payload, key = seen[0]
    assert payload == {"model": "text-embedding-3-small", "input": ["a", " ", "c"]}
    assert key == "sk-test"
    assert X.shape == (3, remote.DIM) and X[2, 0] == 2.0   # rows put back in input order


def test_openai_bad_key_is_unavailable_not_retried(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bad")
    calls = []

    def post(payload, key):
        calls.append(1)
        raise urllib.error.HTTPError(remote.URL, 401, "no", {}, io.BytesIO(b"{}"))

    with pytest.raises(EmbeddingUnavailable, match="refused the key"):
        remote.embed_openai(["a"], post=post)
    assert len(calls) == 1


# ------------------------------------------------------------------ status

def test_status_reports_every_backend_without_loading_anything(monkeypatch):
    monkeypatch.setattr(neural, "dependencies_missing", lambda: "pip install 'spreadex[neural]'")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st = embedding_status("unixcoder")
    by = {b["id"]: b for b in st["backends"]}
    assert set(by) == {"unixcoder", "openai", "tfidf"}
    assert not by["unixcoder"]["ready"] and "spreadex[neural]" in by["unixcoder"]["fix"]
    assert not by["openai"]["ready"] and by["tfidf"]["ready"]
    assert st["fallback_to"] == "tfidf"


# ---------------------------------------------------- the real model, if present

@pytest.mark.skipif(neural.dependencies_missing() is not None or not neural.is_downloaded(),
                    reason="UniXcoder is not installed and cached on this machine")
def test_real_unixcoder_is_deterministic_and_cls_shaped(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    a = neural.embed_unixcoder(TEXTS[:3])
    b = neural.embed_unixcoder(list(reversed(TEXTS[:3])))
    assert a.shape == (3, neural.DIM)
    assert np.array_equal(a, b[::-1])          # an input's vector does not depend on its neighbours
