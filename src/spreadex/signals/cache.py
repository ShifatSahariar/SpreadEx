"""Embedding cache: one vector per (backend, input text), kept across campaigns.

A neural embedding is the slowest step a campaign takes before execution, and an OpenAI one
costs money, so a text is embedded once per backend. The key includes everything that changes a
vector (model, revision, pooling, truncation), so a backend change is a cache miss rather than a
stale hit.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Callable, Sequence

import numpy as np


def _key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class EmbeddingCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE IF NOT EXISTS vectors (backend TEXT, key TEXT, dim INTEGER, "
                     "vec BLOB, PRIMARY KEY (backend, key))")
        return conn

    def embed(self, backend: str, texts: Sequence[str],
              compute: Callable[[Sequence[str]], np.ndarray]) -> tuple[np.ndarray, int]:
        """Vectors for `texts`, computing only the ones not cached. Returns (vectors, n_computed)."""
        if self.path is None:
            return np.asarray(compute(texts), dtype=np.float64), len(texts)
        keys = [_key(t) for t in texts]
        found: dict[str, np.ndarray] = {}
        with self._connect() as conn:
            for i in range(0, len(keys), 500):
                chunk = list(dict.fromkeys(keys[i:i + 500]))
                marks = ",".join("?" * len(chunk))
                for k, dim, blob in conn.execute(
                        f"SELECT key, dim, vec FROM vectors WHERE backend=? AND key IN ({marks})",
                        [backend, *chunk]):
                    found[k] = np.frombuffer(blob, dtype=np.float32, count=dim)
        todo = list(dict.fromkeys(k for k in keys if k not in found))
        if todo:
            text_of = dict(zip(keys, texts))
            fresh = np.asarray(compute([text_of[k] for k in todo]), dtype=np.float32)
            with self._connect() as conn:
                conn.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                                 [(backend, k, v.size, v.tobytes()) for k, v in zip(todo, fresh)])
            found.update(zip(todo, fresh))
        return np.vstack([found[k] for k in keys]).astype(np.float64), len(todo)
