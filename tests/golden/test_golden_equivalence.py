"""PHASE 3 GATE: tool implementation == research implementation.

Every assertion here compares spreadex.prioritization.reference against the
actual ICST 2026 code. If any of these fail, the tool is no longer computing
the published algorithm and no further work should proceed.
"""

from __future__ import annotations

import numpy as np
import pytest

from spreadex.prioritization import reference as ref

from _research import requires_research

pytestmark = requires_research

SEED = 42


def cluster_both(corpus, research):
    """Cluster once with a pinned seed and hand both sides identical input."""
    embeddings, _ = corpus
    clusters, exemplar_map = ref.cluster_once(embeddings, random_state=SEED)
    return embeddings, clusters, exemplar_map


# ---------------------------------------------------------------- clustering

def test_our_normalization_matches_the_research_prioritization_path(corpus):
    embeddings, _ = corpus
    ids = list(embeddings)
    X = np.vstack([embeddings[i] for i in ids])
    theirs = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-8)
    np.testing.assert_allclose(ref.l2_normalize_eps(X), theirs, rtol=0, atol=0)


def test_k_effective_matches_research_perform_clustering(corpus, research):
    """K_eff must agree with FUZZ_TOOL_SELECTION's own computation."""
    embeddings, _ = corpus
    ids = list(embeddings)
    vectors = [embeddings[i] for i in ids]
    id2label, k_eff_theirs, _ = research["perform_clustering"](
        vectors, ids, algo="Affinity", random_seed=SEED
    )
    labels = np.array([id2label[i] for i in ids])
    assert ref.k_effective(labels) == k_eff_theirs


# ------------------------------------------------------------ cluster order

def test_cluster_ordering_is_identical(corpus, research):
    embeddings, clusters, _ = cluster_both(corpus, research)
    ours = ref.centroid_spread_order(clusters, embeddings)
    theirs = research["cluster_by_centroid_spread"](clusters, embeddings)
    assert ours == theirs, "CentroidSpread cluster ordering diverged"


def test_cluster_ordering_is_a_permutation_of_the_clusters(corpus, research):
    embeddings, clusters, _ = cluster_both(corpus, research)
    order = ref.centroid_spread_order(clusters, embeddings)
    assert sorted(map(str, order)) == sorted(map(str, clusters))


def test_cluster_ordering_tie_break_on_equal_sizes(research):
    """Equal-sized clusters must break the tie by centroid isolation, the same
    way on both sides -- this is the path the reference calls 'Algorithm 1,
    refined', and it is where a naive port silently differs."""
    embeddings = {
        "a0": np.array([1.0, 0.0]), "a1": np.array([0.99, 0.01]),
        "b0": np.array([0.0, 1.0]), "b1": np.array([0.01, 0.99]),
        "c0": np.array([-1.0, 0.0]), "c1": np.array([-0.99, 0.01]),
    }
    clusters = {0: ["a0", "a1"], 1: ["b0", "b1"], 2: ["c0", "c1"]}  # all size 2
    assert ref.centroid_spread_order(clusters, embeddings) == \
        research["cluster_by_centroid_spread"](clusters, embeddings)


# --------------------------------------------------------- in-cluster order

def test_within_cluster_ordering_is_identical(corpus, research):
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    ours = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)
    theirs = research["inputs_by_exemplar_distance"](clusters, embeddings, exemplar_map)
    assert ours == theirs, "ExemplarDistance ordering diverged"


def test_published_direction_is_closest_first(corpus, research):
    """SpreadEx_RR uses the 'closest' default; the webapp's farthest-first is
    the deviation, and it must NOT be what we compute."""
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    closest = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map, "closest")
    farthest = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map, "farthest")
    default = research["inputs_by_exemplar_distance"](clusters, embeddings, exemplar_map)
    assert closest == default
    assert any(closest[c] != farthest[c] for c in clusters if len(clusters[c]) > 1)


# ------------------------------------------------------------- final order

@pytest.mark.parametrize("budgets", [
    [1, 2, 3, 4, 5],
    [5, 10, 15, 20],
    [10, 20, 30, 40, 45],
    list(range(1, 46)),
])
def test_final_spreadex_ordering_is_identical(corpus, research, budgets):
    """The published ordering, driven through the real budget loop."""
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    order = ref.centroid_spread_order(clusters, embeddings)
    ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)

    ours, _ = ref.drive_budgets(order, ranking, budgets)

    their_selector = research["create_round_robin_cluster_selector"](order, ranking)
    previously, theirs, last = set(), [], 0
    for budget in budgets:
        new = their_selector(clusters=clusters, previously_selected=previously,
                             needed_inputs=budget - last, embeddings=embeddings)
        for inp in new:
            if inp not in previously:
                theirs.append(inp)
        previously.update(new)
        last = len(previously)

    assert ours == theirs, f"SpreadEx ordering diverged at budgets={budgets}"


def test_budget_truncation_is_a_prefix(corpus, research):
    """Selection is cumulative: each budget's snapshot extends the previous one."""
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    order = ref.centroid_spread_order(clusters, embeddings)
    ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)

    budgets = [5, 10, 20, 45]
    _, snapshots = ref.drive_budgets(order, ranking, budgets)
    for a, b in zip(budgets, budgets[1:]):
        assert snapshots[b][: len(snapshots[a])] == snapshots[a]


def test_one_pass_quirk_is_reproduced(corpus, research):
    """A single call for more than K inputs returns at most one per cluster.

    This is a quirk of the research selector, not a desirable property. It is
    pinned so that 'fixing' it becomes a deliberate, visible decision.
    """
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    order = ref.centroid_spread_order(clusters, embeddings)
    ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)
    K = len(order)

    ours = ref.RoundRobinSelector(order, ranking).select(set(), 1000)
    theirs = research["create_round_robin_cluster_selector"](order, ranking)(
        clusters=clusters, previously_selected=set(), needed_inputs=1000, embeddings=embeddings
    )
    assert ours == theirs
    assert len(ours) <= K


def test_full_ordering_covers_the_whole_corpus(corpus, research):
    """Our convenience wrapper must still be the reference process, and must
    reach every input -- no input may be unreachable at any budget."""
    embeddings, clusters, exemplar_map = cluster_both(corpus, research)
    order = ref.centroid_spread_order(clusters, embeddings)
    ranking = ref.exemplar_distance_ranking(clusters, embeddings, exemplar_map)
    n = len(embeddings)

    full = ref.full_ordering(order, ranking, n)
    assert len(full) == n
    assert set(full) == set(embeddings)

    driven, _ = ref.drive_budgets(order, ranking, list(range(1, n + 1)))
    assert full == driven
