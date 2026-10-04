"""Verify the published algorithms WITHOUT the research repository.

tests/golden/ imports the real ICST 2026 code and is the authority, but it
needs a checkout nobody outside this project has. These frozen outputs come
from that code (see scripts/freeze_golden.py) and let any clone -- and
ordinary CI -- check that this implementation still computes the published
numbers, rather than merely that it runs.

If one of these fails, do NOT re-freeze the fixture. Re-freezing turns a
regression into a rename.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spreadex.prioritization import reference as ref

FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "icst2026_reference.json"


@pytest.fixture(scope="module")
def frozen() -> dict:
    assert FIXTURE.is_file(), f"missing {FIXTURE}; run scripts/freeze_golden.py"
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def corpus():
    """Byte-identical to tests/golden/conftest.py -- the fixture was frozen on
    exactly this corpus, so the two must not drift apart."""
    rng = np.random.default_rng(20260929)
    embeddings: dict[str, np.ndarray] = {}
    generators: dict[str, str] = {}

    def blob(prefix, gen, centre, n, spread=0.05):
        for i in range(n):
            key = f"{prefix}_{i}"
            embeddings[key] = np.asarray(centre, dtype=float) + rng.normal(0, spread, len(centre))
            generators[key] = gen

    blob("alpha", "genA", [1.0, 0.0, 0.0, 0.0], 12)
    blob("beta", "genB", [0.0, 1.0, 0.0, 0.0], 12)
    blob("gamma", "genC", [0.0, 0.0, 1.0, 0.0], 8)
    blob("delta", "genA", [0.0, 0.0, 0.0, 1.0], 8)
    blob("eps", "genB", [0.7, 0.7, 0.0, 0.0], 5)
    return embeddings, generators


@pytest.fixture(scope="module")
def clustered(corpus, frozen):
    embeddings, _ = corpus
    return ref.cluster_once(embeddings, random_state=frozen["seed"])


def test_the_corpus_has_not_drifted(corpus, frozen):
    """Everything else is meaningless if the inputs are not the frozen ones."""
    embeddings, _ = corpus
    assert len(embeddings) == len(frozen["id_to_label"])
    assert set(embeddings) == set(frozen["id_to_label"])


def test_clustering_reproduces_the_research_partition(clustered, frozen):
    clusters, _ = clustered
    assert sorted(len(m) for m in clusters.values()) == frozen["cluster_sizes"]
    id_to_label = {i: label for label, members in clusters.items() for i in members}
    ours = {frozenset(m) for m in clusters.values()}
    theirs: dict = {}
    for name, label in frozen["id_to_label"].items():
        theirs.setdefault(label, []).append(name)
    assert ours == {frozenset(m) for m in theirs.values()}
    assert len(id_to_label) == len(frozen["id_to_label"])


def test_k_effective_matches(clustered, corpus, frozen):
    clusters, _ = clustered
    embeddings, _ = corpus
    id_to_label = {i: label for label, members in clusters.items() for i in members}
    labels = np.array([id_to_label[i] for i in embeddings])
    assert ref.k_effective(labels) == frozen["k_eff"]


def test_cluster_coverage_matches_the_research_values(clustered, corpus, frozen):
    """CC(g) = distinct clusters g touches, over K_eff."""
    clusters, _ = clustered
    _, generators = corpus
    id_to_label = {i: label for label, members in clusters.items() for i in members}
    gens = sorted(set(generators.values()))
    ours = ref.cluster_coverage(id_to_label, generators, gens, frozen["k_eff"])
    for gen, expected in frozen["cluster_coverage"].items():
        assert ours[gen] == pytest.approx(expected), gen


def test_the_prioritized_ordering_is_the_published_one(clustered, corpus, frozen):
    """SpreadEx_RR: CentroidSpread over clusters x ExemplarDistance within
    them, emitted round-robin. This is the ordering a user's campaign executes
    in, so a drift here changes results silently."""
    clusters, exemplars = clustered
    embeddings, _ = corpus
    order = ref.centroid_spread_order(clusters, embeddings)
    ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplars)
    ours = ref.full_ordering(order, ranking, len(embeddings))
    assert ours == frozen["prioritized_order"]


def test_the_fixture_says_where_it_came_from(frozen):
    """A number nobody can regenerate is not evidence."""
    assert "freeze_golden" in frozen["_what"]
    assert (Path(__file__).parents[1] / "scripts" / "freeze_golden.py").is_file()
