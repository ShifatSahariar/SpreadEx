"""SelectionSignal: how a corpus is scored and ordered before execution.

Cluster Coverage is ONE implementation, not the architecture. k-path structural
diversity and cost/validity signals are others. Keeping this a protocol is
deliberate insurance: if a cheaper deterministic signal turns out to work as
well, that becomes `--selection-signal kpath` rather than a redesign.

The CC implementation delegates every algorithmic step to
spreadex.prioritization.reference, which is pinned against the published
research code by tests/golden/. Nothing in this module reimplements the
algorithm.
"""

from __future__ import annotations

import os
import warnings

from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np
from sklearn.exceptions import ConvergenceWarning

from ..prioritization import reference as ref


@dataclass(frozen=True)
class Item:
    """One generated input, as the signal layer sees it."""

    blob_hash: str
    text: str
    generator: str


@dataclass
class Ordering:
    """A prioritized order over a corpus, plus why it looks the way it does."""

    order: list[int]                                    # indices into the item list
    generator_scores: dict[str, float] = field(default_factory=dict)
    k_eff: int | None = None
    detail: str = ""
    #: Things the user should know about how much this ordering can be trusted.
    #: Reported, never swallowed: a caveat the tool keeps to itself is worse
    #: than no caveat, because the numbers look just as confident either way.
    caveats: list[str] = field(default_factory=list)
    #: Which embedding backend built the diversity map (EmbeddingInfo.as_dict()), or None.
    embedding: dict | None = None
    #: How the map was clustered: damping used and whether it converged.
    clustering: dict | None = None
    #: Which SpreadEx ordering produced `order` (published Algorithm 1, or the replication code's).
    prioritization: dict | None = None


class SelectionSignal(Protocol):
    name: str

    def rank(self, items: Sequence[Item], seed: int = 42) -> Ordering: ...


# --------------------------------------------------------------------- embed

def embed_tfidf(texts: Sequence[str]) -> np.ndarray:
    """Default embedding: character n-grams. No torch, no GPU, no API key."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=4096, min_df=1)
    safe = [t if t.strip() else " " for t in texts]
    return np.asarray(vec.fit_transform(safe).todense(), dtype=np.float64)


#: The embedding backends a diversity map can be built on. UniXcoder is the default: it is one of
#: the models the ICST 2026 study evaluated and runs on this machine. OpenAI's model is the one the
#: study's prioritization experiments used, and is opt-in because it sends inputs to OpenAI.
#: TF-IDF needs nothing and is what a campaign falls back to when the others cannot run.
EMBEDDING_MODELS = ("unixcoder", "openai", "tfidf")
PRIORITIZATION_VARIANTS = ("published", "replication")
DEFAULT_EMBEDDING = "unixcoder"
#: What to try next when a backend cannot run here. A fallback is never silent: it becomes a
#: caveat on the campaign and is recorded in its manifest.
_FALLBACK_CHAIN = {"openai": ("unixcoder", "tfidf"), "unixcoder": ("tfidf",), "tfidf": ()}


def default_embedding() -> str:
    """The backend used when spreadex.yaml does not name one.

    SPREADEX_DEFAULT_EMBEDDING overrides it (the test suite sets tfidf, so it neither downloads
    a model nor spends minutes embedding); an explicit `embedding.model` always wins over both.
    """
    value = (os.environ.get("SPREADEX_DEFAULT_EMBEDDING") or DEFAULT_EMBEDDING).strip().lower()
    return value if value in EMBEDDING_MODELS else DEFAULT_EMBEDDING


@dataclass
class EmbeddingInfo:
    """Which backend actually produced the vectors, and why, for the log and the manifest."""

    requested: str
    used: str
    cache_id: str
    dim: int = 0
    computed: int = 0
    cached: int = 0
    fallback_reason: str | None = None

    def as_dict(self) -> dict:
        return {"requested": self.requested, "used": self.used, "backend": self.cache_id,
                "dim": self.dim, "computed": self.computed, "cached": self.cached,
                **({"fallback_reason": self.fallback_reason} if self.fallback_reason else {})}


def _embed_one(model: str, texts: Sequence[str], cache, device: str, log) -> tuple[np.ndarray, str, int]:
    if model == "tfidf":
        # Fitted on this pool, so a vector means nothing outside it: never cached.
        return embed_tfidf(texts), "tfidf:char_wb:2-4:4096", len(texts)
    if model == "unixcoder":
        from . import neural
        neural._load(device, log)  # raises EmbeddingUnavailable before any work is done
        X, n = cache.embed(neural.CACHE_ID, texts, lambda ts: neural.embed_unixcoder(ts, device, log))
        return X, neural.CACHE_ID, n
    if model == "openai":
        from . import remote
        X, n = cache.embed(remote.CACHE_ID, texts, lambda ts: remote.embed_openai(ts, log))
        return X, remote.CACHE_ID, n
    raise ValueError(f"Unknown embedding model {model!r}. Available: {', '.join(EMBEDDING_MODELS)}")


def embed_pool(texts: Sequence[str], model: str | None = None, *, fallback: bool = True,
               cache_path=None, device: str = "cpu",
               log=lambda _m: None) -> tuple[np.ndarray, EmbeddingInfo]:
    """Embed a pool with the requested backend, falling back down the chain if it cannot run."""
    from .cache import EmbeddingCache
    from .neural import EmbeddingUnavailable

    requested = (model or default_embedding()).lower()
    if requested not in EMBEDDING_MODELS:
        raise ValueError(f"Unknown embedding model {requested!r}. Available: {', '.join(EMBEDDING_MODELS)}")
    cache = EmbeddingCache(cache_path)
    reasons: list[str] = []
    for candidate in (requested, *(_FALLBACK_CHAIN[requested] if fallback else ())):
        try:
            X, cache_id, computed = _embed_one(candidate, texts, cache, device, log)
        except EmbeddingUnavailable as exc:
            if not fallback:
                raise RuntimeError(f"{exc}\n  (embedding.fallback is `none`, so the campaign stops here.)") from exc
            reasons.append(f"{candidate}: {exc}")
            log(f"  ! {candidate} embeddings unavailable, trying {_next_after(requested, candidate)}: {exc}")
            continue
        return X, EmbeddingInfo(requested=requested, used=candidate, cache_id=cache_id,
                                dim=int(X.shape[1]) if X.ndim == 2 else 0, computed=computed,
                                cached=len(texts) - computed,
                                fallback_reason="; ".join(reasons) or None)
    raise RuntimeError("No embedding backend could run: " + "; ".join(reasons))


def _next_after(requested: str, candidate: str) -> str:
    chain = (requested, *_FALLBACK_CHAIN[requested])
    i = chain.index(candidate)
    return chain[i + 1] if i + 1 < len(chain) else "nothing"


def embed(texts: Sequence[str], model: str = "tfidf") -> np.ndarray:
    """Vectors only, no fallback. Kept for callers that want exactly one backend."""
    return embed_pool(texts, model, fallback=False)[0]


# ------------------------------------------------------------------- signals

class RandomSignal:
    """Baseline. A budget curve means nothing without something to beat."""

    name = "random"

    def rank(self, items: Sequence[Item], seed: int = 42) -> Ordering:
        import random

        idx = list(range(len(items)))
        random.Random(seed).shuffle(idx)
        return Ordering(order=idx,
                        generator_scores={i.generator: 0.0 for i in items},
                        detail="random baseline")


class ClusterCoverageSignal:
    """The SpreadEx diversity map: one clustering, two readouts.

    Readout 1 -- per-generator Cluster Coverage, for allocating *generation*
    budget. Readout 2 -- CentroidSpread x ExemplarDistance emitted round-robin,
    for allocating *execution* budget.

    The union of all generators' inputs is ordered, rather than collapsing to a
    single winning generator: the clustering is shared, so discarding the
    runners-up throws away information already paid for. `select_generator()`
    exposes the published single-winner RankSum selection separately.
    """

    name = "cc"

    def __init__(self, embedding_model: str | None = None, random_state: int | None = 42, *,
                 fallback: bool = True, cache_path=None, device: str = "cpu",
                 log=lambda _m: None, variant: str = "published") -> None:
        if variant not in PRIORITIZATION_VARIANTS:
            raise ValueError(f"Unknown prioritization variant {variant!r}: "
                             f"{', '.join(PRIORITIZATION_VARIANTS)}")
        #: "published": Algorithm 1 as printed in the ICST 2026 paper (prioritization/published.py).
        #: "replication": the replication code's ordering, which produced the paper's results.
        self.variant = variant
        self.embedding_model = (embedding_model or default_embedding()).lower()
        self.fallback = fallback
        self.cache_path = cache_path
        self.device = device
        self.log = log
        # The research code calls AffinityPropagation() with no random_state.
        # We pin it by default so campaigns are reproducible; pass None to match
        # the reference exactly.
        self.random_state = random_state

    #: Measured, not guessed: scripts/scale_audit.py gave 2.5 GB at n=5000 and
    #: 6.3 GB at n=10000, which is what a handful of float64 n-by-n matrices
    #: costs. Fitted at the large end on purpose -- below a few thousand the
    #: figure is mostly interpreter and sklearn baseline rather than
    #: clustering, and the guard only acts where the quadratic dominates.
    #: Rounded UP, because underestimating is the direction that OOMs.
    BYTES_PER_PAIR = 70

    @classmethod
    def estimated_bytes(cls, n: int) -> int:
        return cls.BYTES_PER_PAIR * n * n

    @staticmethod
    def _physical_memory_bytes() -> int | None:
        try:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError, AttributeError):
            return None

    def _memory_guard(self, n: int) -> list[str]:
        """Affinity Propagation is O(n^2) in memory and will take the machine
        down with it rather than degrade.

        A campaign that OOMs loses every input it generated, so this is checked
        before the allocation rather than discovered during it.
        """
        total = self._physical_memory_bytes()
        need = self.estimated_bytes(n)
        if total is None or need < 0.25 * total:
            return []
        gb = need / 1024 ** 3
        if need > 0.70 * total:
            raise MemoryError(
                f"Clustering {n:,} inputs needs roughly {gb:.1f} GB, and this "
                f"machine has {total / 1024 ** 3:.0f} GB.\n"
                f"  Affinity Propagation is O(n^2) in memory; it does not "
                f"degrade, it fails.\n"
                f"  Fix: cap the pool with `budget: {{max_inputs: 5000}}`, lower "
                f"`generation.cap`\n"
                f"       or `generation.per_generator`, or use "
                f"`selection_signal: random` for this run."
            )
        return [
            f"Clustering {n:,} inputs is expected to need about {gb:.1f} GB of "
            f"memory, on a machine with {total / 1024 ** 3:.0f} GB. Affinity "
            f"Propagation grows as the square of the corpus, so a larger pool "
            f"may not complete at all. `budget.max_inputs` caps it."
        ]

    #: sklearn's default, which is what the published research code used.
    DEFAULT_DAMPING = 0.5
    #: Tried once when the default does not converge (e.g. UniXcoder vectors of Rhino inputs).
    RETRY_DAMPING = 0.9

    def _cluster(self, embeddings, damping: float):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            clusters, exemplar_map = ref.cluster_once(
                embeddings, random_state=self.random_state, damping=damping)
        converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
        return clusters, exemplar_map, converged

    def rank(self, items: Sequence[Item], seed: int = 42) -> Ordering:
        n = len(items)
        if n == 0:
            return Ordering([], {}, 0, "empty corpus")
        if n == 1:
            return Ordering([0], {items[0].generator: 1.0}, 1, "single input")

        X, info = embed_pool([i.text for i in items], self.embedding_model, fallback=self.fallback,
                             cache_path=self.cache_path, device=self.device, log=self.log)
        embeddings = {i: X[i] for i in range(n)}

        # Affinity Propagation can fail to converge, and when it does sklearn
        # says so in a warning that reaches the user as a stack trace from a
        # file they have never heard of. It matters -- degenerate centers mean
        # the clusters CC is measured over are not trustworthy -- so it is
        # caught and reported in the tool's own words instead.
        caveats: list[str] = list(self._memory_guard(n))
        if info.used != info.requested:
            caveats.append(
                f"The diversity map was built with {_LABELS[info.used]} instead of "
                f"{_LABELS[info.requested]}, which could not run here ({info.fallback_reason}). "
                f"Cluster Coverage and the ordering are not comparable with campaigns that used "
                f"{_LABELS[info.requested]}."
            )
        clusters, exemplar_map, converged = self._cluster(embeddings, self.DEFAULT_DAMPING)
        clustering = {"algorithm": "affinity_propagation", "damping": self.DEFAULT_DAMPING,
                      "converged": converged}
        if not converged:
            # The published setting oscillated. Heavier damping is the standard remedy for
            # Affinity Propagation; it is tried once, used only if it converges, and recorded,
            # so a campaign whose default clustering converges is exactly the published one.
            retry = self._cluster(embeddings, self.RETRY_DAMPING)
            if retry[2]:
                clusters, exemplar_map = retry[0], retry[1]
                clustering = {"algorithm": "affinity_propagation", "damping": self.RETRY_DAMPING,
                              "converged": True, "default_damping_converged": False}
                caveats.append(
                    f"Affinity Propagation did not converge with its default damping "
                    f"({self.DEFAULT_DAMPING}), so the diversity map was clustered again with "
                    f"damping {self.RETRY_DAMPING}, which converged. This differs from the "
                    f"published configuration and is recorded in the manifest."
                )
            else:
                clustering["retry_damping"] = self.RETRY_DAMPING
                caveats.append(
                    "Affinity Propagation did not converge on this corpus, even with heavier "
                    "damping, so the clusters may be degenerate and the CC values below are "
                    "weaker evidence than usual. The prioritized ordering is still a valid "
                    "ordering. More inputs, or fewer near-identical ones, usually fixes it."
                )
        labels = np.empty(n, dtype=int)
        for label, members in clusters.items():
            for m in members:
                labels[m] = label
        k_eff = ref.k_effective(labels)

        generator_order = sorted({i.generator for i in items})
        id_to_label = {i: int(labels[i]) for i in range(n)}
        id_to_generator = {i: items[i].generator for i in range(n)}
        scores = ref.cluster_coverage(id_to_label, id_to_generator, generator_order, k_eff)

        from ..prioritization import prioritize
        order, prioritization = prioritize(self.variant, clusters, embeddings, exemplar_map)

        # Anything the reference process never reaches still deserves to run, last.
        seen = set(order)
        order.extend(i for i in range(n) if i not in seen)

        return Ordering(order=order, generator_scores=scores, k_eff=k_eff,
                        detail=f"{k_eff} clusters over {n} inputs ({_LABELS[info.used]})",
                        caveats=caveats, embedding=info.as_dict(), clustering=clustering,
                        prioritization=prioritization)

    @staticmethod
    def select_generator(per_run_coverage, candidate_generators):
        """Published RankSum selection: rank by CC per run, sum, lowest wins."""
        return ref.ranksum_select(per_run_coverage, candidate_generators)


SIGNALS = {"cc": ClusterCoverageSignal, "random": RandomSignal}


_LABELS = {"unixcoder": "UniXcoder", "openai": "OpenAI text-embedding-3-small", "tfidf": "TF-IDF"}


def make_signal(name: str, embedding_model: str | None = None, **options) -> SelectionSignal:
    """`options` go to ClusterCoverageSignal: fallback, cache_path, device, log."""
    key = (name or "cc").lower()
    if key == "random":
        return RandomSignal()
    if key == "cc":
        return ClusterCoverageSignal(embedding_model=embedding_model, **options)
    if key == "kpath":
        raise ValueError(
            "selection signal 'kpath' is not implemented yet (experimental). Use 'cc' or 'random'."
        )
    raise ValueError(f"Unknown selection signal {name!r}. Available: {', '.join(sorted(SIGNALS))}")
