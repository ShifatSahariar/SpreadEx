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


def embed(texts: Sequence[str], model: str = "tfidf") -> np.ndarray:
    if model in ("tfidf", "", None):
        return embed_tfidf(texts)
    if model in ("unixcoder", "graph_codebert", "qwen3"):
        try:
            from .neural import embed_transformer
        except ImportError as exc:
            raise RuntimeError(
                f"Embedding model {model!r} needs the neural extra.\n"
                f"  Fix: pip install 'spreadex[neural]'  (or set embedding.model: tfidf)"
            ) from exc
        return embed_transformer(texts, model)
    raise ValueError(f"Unknown embedding model: {model!r}")


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

    def __init__(self, embedding_model: str = "tfidf", random_state: int | None = 42) -> None:
        self.embedding_model = embedding_model
        # The research code calls AffinityPropagation() with no random_state.
        # We pin it by default so campaigns are reproducible; pass None to match
        # the reference exactly.
        self.random_state = random_state

    def rank(self, items: Sequence[Item], seed: int = 42) -> Ordering:
        n = len(items)
        if n == 0:
            return Ordering([], {}, 0, "empty corpus")
        if n == 1:
            return Ordering([0], {items[0].generator: 1.0}, 1, "single input")

        X = embed([i.text for i in items], self.embedding_model)
        embeddings = {i: X[i] for i in range(n)}

        # Affinity Propagation can fail to converge, and when it does sklearn
        # says so in a warning that reaches the user as a stack trace from a
        # file they have never heard of. It matters -- degenerate centers mean
        # the clusters CC is measured over are not trustworthy -- so it is
        # caught and reported in the tool's own words instead.
        caveats: list[str] = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            clusters, exemplar_map = ref.cluster_once(
                embeddings, random_state=self.random_state)
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            caveats.append(
                "Affinity Propagation did not converge on this corpus, so the clusters "
                "may be degenerate and the CC values below are weaker evidence than "
                "usual. The prioritized ordering is still a valid ordering. More inputs, "
                "or fewer near-identical ones, usually fixes it."
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

        cluster_order = ref.centroid_spread_order(clusters, embeddings)
        ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)
        order = ref.full_ordering(cluster_order, ranking, n)

        # Anything the reference process never reaches still deserves to run, last.
        seen = set(order)
        order.extend(i for i in range(n) if i not in seen)

        return Ordering(order=order, generator_scores=scores, k_eff=k_eff,
                        detail=f"{k_eff} clusters over {n} inputs", caveats=caveats)

    @staticmethod
    def select_generator(per_run_coverage, candidate_generators):
        """Published RankSum selection: rank by CC per run, sum, lowest wins."""
        return ref.ranksum_select(per_run_coverage, candidate_generators)


SIGNALS = {"cc": ClusterCoverageSignal, "random": RandomSignal}


def make_signal(name: str, embedding_model: str = "tfidf") -> SelectionSignal:
    key = (name or "cc").lower()
    if key == "random":
        return RandomSignal()
    if key == "cc":
        return ClusterCoverageSignal(embedding_model=embedding_model)
    if key == "kpath":
        raise ValueError(
            "selection signal 'kpath' is not implemented yet (experimental). Use 'cc' or 'random'."
        )
    raise ValueError(f"Unknown selection signal {name!r}. Available: {', '.join(sorted(SIGNALS))}")
