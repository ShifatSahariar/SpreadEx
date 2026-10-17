"""SpreadEx as published (ICST 2026, Algorithm 1 and Sec. IV-B), checked against the paper itself.

The expected orderings below are derived by hand from the published rules, step by step in each
docstring; they are not outputs of the implementation. The property tests then check every rule
on clusterings the hand cases cannot cover.

The replication code's ordering (`variant: replication`) is checked separately against the research
code by tests/golden and tests/test_golden_fixtures.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from spreadex.prioritization import published
from spreadex.prioritization import reference as ref

# Pool order (insertion order) is x1, x2, x3, y1, y2, z1, z2.
EMB = {
    "x1": np.array([10.0, 0.0]), "x2": np.array([12.0, 0.0]), "x3": np.array([17.0, 0.0]),
    "y1": np.array([0.0, 10.0]), "y2": np.array([0.0, 14.0]),
    "z1": np.array([10.0, 10.0]), "z2": np.array([11.0, 11.0]),
}
CLUSTERS = {0: ["x1", "x2", "x3"], 1: ["y1", "y2"], 2: ["z1", "z2"]}


def test_hand_derived_exemplars():
    """Line 15, exemplar = member closest to the centroid (mean):
    C0 centroid (13,0): |x1|=3, |x2|=1, |x3|=4  -> x2.
    C1 centroid (0,12): |y1|=2, |y2|=2, a tie   -> y1 (first in the pool).
    C2 centroid (10.5,10.5): z1 and z2 both at sqrt(0.5), a tie -> z1."""
    assert published.exemplar_closest_to_centroid(CLUSTERS, EMB) == {0: "x2", 1: "y1", 2: "z1"}


def test_hand_derived_within_cluster_order_is_farthest_first():
    """Lines 16-18, descending distance from the exemplar:
    C0 from x2: x3=5, x1=2, x2=0 -> x3, x1, x2.   C1 from y1: y2=4, y1=0 -> y2, y1.
    C2 from z1: z2=sqrt(2), z1=0 -> z2, z1."""
    ex = published.exemplar_closest_to_centroid(CLUSTERS, EMB)
    assert published.farthest_first_ranking(CLUSTERS, EMB, ex) == {
        0: ["x3", "x1", "x2"], 1: ["y2", "y1"], 2: ["z2", "z1"]}


def test_hand_derived_cluster_order():
    """Lines 1-13. Centroid directions: C0 at 0 deg, C1 at 90 deg, C2 at 45 deg; cosine distances
    d(C0,C1)=1, d(C0,C2)=d(C1,C2)=1-cos45=0.2929.
    Smallest size is 2: C1 and C2 tie. Mean distance to all other clusters: C1 (1+0.2929)/2=0.646,
    C2 (0.2929+0.2929)/2=0.2929 -> C1 first.
    Next, max over remaining of min distance to {C1}: C0=1, C2=0.2929 -> C0. Then C2."""
    assert published.cluster_order(CLUSTERS, EMB) == [1, 0, 2]


def test_hand_derived_full_sequence_is_round_robin():
    """Lines 21-30, one input per cluster per round in cluster order [C1, C0, C2]:
    round 1: y2, x3, z2;  round 2: y1, x1, z1;  round 3: x2 (C1 and C2 are exhausted)."""
    order, meta = published.prioritize(CLUSTERS, EMB)
    assert order == ["y2", "x3", "z2", "y1", "x1", "z1", "x2"]
    assert meta["within_cluster"] == "farthest_first" and meta["exemplar"] == "closest_to_centroid"


def test_the_replication_ordering_differs_where_the_paper_and_its_code_differ():
    """The replication code ranks closest first from Affinity Propagation's exemplar. Given the same
    exemplars, its within-cluster order is exactly the reverse of the published one."""
    ex = published.exemplar_closest_to_centroid(CLUSTERS, EMB)
    closest = ref.exemplar_distance_ranking(CLUSTERS, EMB, ex, direction="closest")
    farthest = published.farthest_first_ranking(CLUSTERS, EMB, ex)
    assert all(closest[c] == list(reversed(farthest[c])) for c in CLUSTERS)


# ------------------------------------------------------------------ properties

def _random_case(seed: int):
    rng = np.random.default_rng(seed)
    emb, clusters, k = {}, {}, int(rng.integers(3, 8))
    for c in range(k):
        centre = rng.normal(0, 1, 6) + 3 * np.eye(6)[c % 6]
        clusters[c] = []
        for j in range(int(rng.integers(1, 9))):
            key = f"c{c}_{j}"
            emb[key] = centre + rng.normal(0, 0.3, 6)
            clusters[c].append(key)
    # Shuffle the pool order so ties are not resolved by construction order by accident.
    keys = list(emb)
    rng.shuffle(keys)
    return {k: emb[k] for k in keys}, clusters


@pytest.mark.parametrize("seed", range(12))
def test_every_published_rule_holds(seed):
    emb, clusters = _random_case(seed)
    order = published.cluster_order(clusters, emb)
    ex = published.exemplar_closest_to_centroid(clusters, emb)
    ranking = published.farthest_first_ranking(clusters, emb, ex)
    sequence, _ = published.prioritize(clusters, emb)
    cent = {c: np.mean([emb[i] for i in m], axis=0) for c, m in clusters.items()}

    def cos(a, b):
        return 1 - float(np.dot(cent[a], cent[b]) / (np.linalg.norm(cent[a]) * np.linalg.norm(cent[b])))

    # The first cluster is a smallest one, the most isolated among them (mean distance to all others).
    smallest = min(len(m) for m in clusters.values())
    assert len(clusters[order[0]]) == smallest
    iso = {c: np.mean([cos(c, o) for o in clusters if o != c]) for c in clusters if len(clusters[c]) == smallest}
    assert iso[order[0]] == pytest.approx(max(iso.values()))
    # Every later cluster maximises the minimum distance to the clusters already chosen.
    for i in range(1, len(order)):
        chosen, rest = order[:i], order[i:]
        best = max(min(cos(r, s) for s in chosen) for r in rest)
        assert min(cos(order[i], s) for s in chosen) == pytest.approx(best)
    for c, members in clusters.items():
        # The exemplar is the member closest to the centroid.
        d = {m: np.linalg.norm(emb[m] - cent[c]) for m in members}
        assert d[ex[c]] == pytest.approx(min(d.values()))
        # Distance from the exemplar never increases along the cluster's ranking.
        dist = [np.linalg.norm(emb[m] - emb[ex[c]]) for m in ranking[c]]
        assert all(a >= b - 1e-12 for a, b in zip(dist, dist[1:]))
    # Round robin: the j-th input taken from a cluster is its j-th ranked member, and in each round
    # the clusters that still have inputs appear in cluster order.
    assert sorted(sequence) == sorted(emb)
    taken = {c: 0 for c in clusters}
    rounds: list[list] = []
    for item in sequence:
        c = next(c for c, m in clusters.items() if item in m)
        assert ranking[c][taken[c]] == item
        if taken[c] >= len(rounds):
            rounds.append([])
        rounds[taken[c]].append(c)
        taken[c] += 1
    for r in rounds:
        assert r == [c for c in order if c in r]


def test_the_ordering_does_not_depend_on_how_clusters_are_numbered():
    """Renumbering the clusters (as a different clustering run might) changes nothing."""
    renamed = {f"k{v}": CLUSTERS[v] for v in (2, 0, 1)}
    order, _ = published.prioritize(renamed, EMB)
    assert order == published.prioritize(CLUSTERS, EMB)[0]


# --------------------------------------------------------- wiring into a campaign

def test_the_signal_executes_the_configured_variant():
    from spreadex.signals.base import ClusterCoverageSignal, Item

    items = [Item(blob_hash=str(i), text=t, generator="g")
             for i, t in enumerate(["1 + 2", "3 * 4 - 5", "x % 0", "((7))", "8 / 2 + 1", "9 - - 9",
                                    "1+1+1+1", "2*2*2", "(1)", "(((2)))", "3 % 4", "5 - 6 - 7"])]
    pub = ClusterCoverageSignal(embedding_model="tfidf", random_state=1).rank(items)
    rep = ClusterCoverageSignal(embedding_model="tfidf", random_state=1, variant="replication").rank(items)
    assert pub.prioritization["variant"] == "published" and rep.prioritization["variant"] == "replication"
    assert sorted(pub.order) == sorted(rep.order) == list(range(len(items)))
    assert pub.generator_scores == rep.generator_scores and pub.k_eff == rep.k_eff   # CC is untouched


def test_the_variant_is_configured_and_validated(tmp_path):
    from spreadex.core.config import ConfigError, load_config

    def cfg(block):
        (tmp_path / "spreadex.yaml").write_text(
            "sut:\n  command: [x, '{input}']\ncorpus:\n  path: ./seeds\ngenerators: []\n" + block)
        (tmp_path / "seeds").mkdir(exist_ok=True)
        return load_config(tmp_path / "spreadex.yaml")

    assert cfg("").prioritization == {"variant": "published"}
    assert cfg("prioritization: {variant: replication}\n").prioritization == {"variant": "replication"}
    assert cfg("").hash() != cfg("prioritization: {variant: replication}\n").hash()
    with pytest.raises(ConfigError, match="published"):
        cfg("prioritization: {variant: farthest}\n")
