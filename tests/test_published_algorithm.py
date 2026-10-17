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
    assert meta["within_cluster"].startswith("farthest first") and meta["exemplar"].startswith("member closest")
    assert meta["sequence"] == order and meta["cluster_order"] == [1, 0, 2]
    assert meta["exemplars"] == {0: "x2", 1: "y1", 2: "z1"}


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


# ------------------------------------------------- the remaining required fixtures

def test_an_exact_tie_among_the_smallest_goes_to_the_first_in_the_pool():
    """Two singleton clusters at 0 and 90 degrees, a larger one at 45 degrees. Both singletons have
    mean distance (1 + 0.2929) / 2 to the others: an exact tie. Published: first in pool order.
    b1 comes first in the pool here, so cluster 'b' leads, whatever the clusters are called."""
    emb = {"b1": np.array([0.0, 4.0]), "a1": np.array([4.0, 0.0]),
           "m1": np.array([3.0, 3.0]), "m2": np.array([5.0, 5.0])}
    for clusters in ({"a": ["a1"], "b": ["b1"], "m": ["m1", "m2"]},
                     {"m": ["m1", "m2"], "b": ["b1"], "a": ["a1"]}):
        assert published.cluster_order(clusters, emb)[0] == "b"


def test_the_two_variants_use_different_exemplars_where_they_differ():
    """Published: the member closest to the centroid (x2, hand-derived above). Replication: whatever
    Affinity Propagation chose -- here, deliberately, x1 -- and closest first from it:
    from x1, x1=0, x2=2, x3=7 -> x1, x2, x3."""
    from spreadex.prioritization import prioritize

    ap = {0: "x1", 1: "y1", 2: "z1"}
    _, pub = prioritize("published", CLUSTERS, EMB, ap)
    seq, rep = prioritize("replication", CLUSTERS, EMB, ap)
    assert pub["exemplars"][0] == "x2" and rep["exemplars"][0] == "x1"
    assert seq.index("x1") < seq.index("x2") < seq.index("x3")


def test_equal_distances_from_the_exemplar_keep_pool_order():
    """w1 is the centroid itself, so the exemplar; w2 and w3 are both at distance 1 from it.
    Published: farthest first, ties in pool order -> w2, w3, then w1."""
    emb = {"w1": np.array([5.0, 5.0]), "w2": np.array([6.0, 5.0]), "w3": np.array([4.0, 5.0])}
    ex = published.exemplar_closest_to_centroid({0: ["w1", "w2", "w3"]}, emb)
    assert ex == {0: "w1"}
    assert published.farthest_first_ranking({0: ["w1", "w2", "w3"]}, emb, ex) == {0: ["w2", "w3", "w1"]}


def test_budgets_give_cumulative_prefixes_without_duplicates():
    """Driving the round-robin with growing budgets (the research loop) yields, at every budget b,
    exactly the first b inputs of the full sequence -- never a repeat."""
    order = published.cluster_order(CLUSTERS, EMB)
    ranking = published.farthest_first_ranking(CLUSTERS, EMB, published.exemplar_closest_to_centroid(CLUSTERS, EMB))
    full, snaps = ref.drive_budgets(order, ranking, list(range(1, len(EMB) + 1)))
    assert full == published.prioritize(CLUSTERS, EMB)[0] and len(set(full)) == len(full)
    for b, snap in snaps.items():
        assert snap == full[:b]
    # The research loop's documented quirk: one jump in budget is served by at most one round, so
    # a jump from 3 to 100 adds only one input per cluster. Campaigns therefore drive the loop one
    # input at a time (full_ordering), which covers the whole pool, as above.
    jump, _ = ref.drive_budgets(order, ranking, [3, 100])
    assert jump == full[:6]
    assert ref.full_ordering(order, ranking, 100) == full


def test_top_k_selection_filters_after_ordering_and_keeps_seeds():
    """Selection removes inputs only produced by dropped generators, keeps the published order of
    the rest, keeps the user's seeds, and keeps an input another kept generator also produced."""
    from types import SimpleNamespace as It

    from spreadex.core.selection import apply

    seq, _ = published.prioritize(CLUSTERS, EMB)                 # y2 x3 z2 y1 x1 z1 x2
    gen = {"x1": "fa", "x2": "fa", "x3": "fb", "y1": "fb", "y2": "corpus", "z1": "fb", "z2": "fa"}
    items = [It(blob_hash=i, generator=gen[i]) for i in seq]
    origins = {i: {gen[i]} for i in seq} | {"z1": {"fb", "fa"}}  # z1 also produced by kept fa
    kept = [it.blob_hash for it in apply(items, origins, dropped=["fb"])]
    assert kept == ["y2", "z2", "x1", "z1", "x2"]                # x3, y1 dropped; order kept
