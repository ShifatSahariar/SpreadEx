"""Bit-faithful port of the published SpreadEx algorithms.

This module is the *specification*. Every function here mirrors a specific
function in the ICST 2026 replication package, and `tests/golden/` asserts that
the two agree on fixed data. Where the research code has a quirk, the quirk is
reproduced here and documented rather than quietly corrected -- a "fix" that
changes the published ordering would invalidate the paper's results.

Provenance (paths relative to the research repository):
  cluster_once          <- PRIORATIZATION/prioritization_utils/prioritization_utils.py::cluster_embeddings_once
  centroid_spread_order <- PRIORATIZATION/input_selection/cluster_strategies/by_centroid_spread.py
  exemplar_distance_ranking
                        <- PRIORATIZATION/input_selection/input_strategies/by_exemplar_distance.py
  RoundRobinSelector    <- PRIORATIZATION/prioritization_utils/run_approaches_combo.py::create_round_robin_cluster_selector
  drive_budgets         <- PRIORATIZATION/prioritization_utils/run_approaches_combo.py::run_deterministic_strategies
  cluster_coverage      <- FUZZ_TOOL_SELECTION/utils/clustering_analysis_utils.py::cluster_coverage_pipeline
  ranksum_select        <- PRIORATIZATION/prioritization_utils/tool_selection_ranksum.py::compute_ranksum_all_models
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Hashable, Mapping, Sequence

import numpy as np

InputId = Hashable
Embeddings = Mapping[InputId, np.ndarray]


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

def l2_normalize_eps(X: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Normalization used by the PRIORATIZATION path: `X /= norm + 1e-8`.

    Note this is NOT sklearn's `normalize()`, which the FUZZ_TOOL_SELECTION
    path uses. The epsilon makes the two differ in the last bits; both are
    reproduced so each side matches its own reference.
    """
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + eps)


def cluster_once(
    embeddings: Embeddings,
    random_state: int | None = None,
) -> tuple[dict[Any, list[InputId]], dict[Any, InputId]]:
    """Affinity Propagation over L2-normalized vectors.

    `random_state=None` reproduces the research default: the published code
    calls `AffinityPropagation()` with no arguments. sklearn then seeds the
    tie-breaking noise from global state, so the reference is not perfectly
    reproducible run to run. Pass an int for deterministic behaviour; the
    golden tests pin both sides to the same value so the comparison is fair.
    """
    from sklearn.cluster import AffinityPropagation

    ids = list(embeddings.keys())
    X = l2_normalize_eps(np.vstack([embeddings[i] for i in ids]))

    model = AffinityPropagation(random_state=random_state)
    labels = model.fit_predict(X)
    exemplar_indices = model.cluster_centers_indices_

    clusters: dict[Any, list[InputId]] = defaultdict(list)
    for name, label in zip(ids, labels):
        clusters[label].append(name)

    # The reference zips SORTED cluster labels against the exemplar index array,
    # relying on AP emitting exemplars in label order. Reproduced exactly.
    exemplar_map: dict[Any, InputId] = {}
    for lbl, idx in zip(sorted(clusters.keys()), exemplar_indices):
        exemplar_map[lbl] = ids[idx]

    return dict(clusters), exemplar_map


# --------------------------------------------------------------------------
# Cluster ordering: CentroidSpread
# --------------------------------------------------------------------------

def compute_centroid(embeddings: Embeddings, ids: Sequence[InputId]) -> np.ndarray:
    """Plain mean -- the reference does NOT re-normalize the centroid here."""
    return np.mean([embeddings[i] for i in ids], axis=0)


def centroid_spread_order(clusters: Mapping[Any, list[InputId]], embeddings: Embeddings) -> list[Any]:
    """Farthest-first traversal over cluster centroids in cosine distance.

    Seed: the smallest cluster. On a size tie, the most isolated centroid
    (greatest mean distance to the others) wins -- the reference calls this the
    "deterministic seed selection (Algorithm 1, refined)".
    """
    from sklearn.metrics.pairwise import cosine_similarity

    if not clusters:
        return []
    valid = {lbl: members for lbl, members in clusters.items() if members}
    if not valid:
        return []

    labels = list(valid.keys())
    centroids = np.array([compute_centroid(embeddings, valid[lbl]) for lbl in labels])
    distance = 1.0 - cosine_similarity(centroids)
    idx_of = {lbl: i for i, lbl in enumerate(labels)}

    min_size = min(len(m) for m in valid.values())
    smallest = [lbl for lbl, m in valid.items() if len(m) == min_size]
    if len(smallest) == 1:
        seed = smallest[0]
    else:
        def isolation(lbl):
            i = idx_of[lbl]
            return np.mean([distance[i, j] for j in range(len(labels)) if j != i])
        # max() keeps the FIRST maximal element, i.e. the earliest label in
        # `valid` insertion order. Reproduced.
        seed = max(smallest, key=isolation)

    selected = [seed]
    selected_idx = {idx_of[seed]}
    remaining = set(range(len(labels))) - selected_idx

    while remaining:
        scored = [(r, min(distance[r, s] for s in selected_idx)) for r in remaining]
        next_idx, _ = max(scored, key=lambda x: x[1])
        selected.append(labels[next_idx])
        selected_idx.add(next_idx)
        remaining.remove(next_idx)

    return selected


# --------------------------------------------------------------------------
# In-cluster ordering: ExemplarDistance
# --------------------------------------------------------------------------

def exemplar_distance_ranking(
    clusters: Mapping[Any, list[InputId]],
    embeddings: Embeddings,
    exemplar_map: Mapping[Any, InputId],
    direction: str = "closest",
) -> dict[Any, list[InputId]]:
    """Rank each cluster's members by Euclidean distance to its exemplar.

    `direction="closest"` is the published SpreadEx_RR configuration: the
    research call site (prioritization_utils.py:205) passes no direction, so the
    function's own "closest" default applies. Most representative member first.

    (For the record: webapp/tool_mode/pipeline.py in the research repository
    hardcodes farthest-first, which silently diverges from the paper.)
    """
    reverse = direction == "farthest"
    ranked: dict[Any, list[InputId]] = {}
    for cid, members in clusters.items():
        if len(members) <= 1:
            ranked[cid] = list(members)
            continue
        ex = embeddings[exemplar_map[cid]]
        vecs = np.array([embeddings[m] for m in members])
        d = np.linalg.norm(vecs - ex, axis=1)
        order = np.argsort(d)[::-1] if reverse else np.argsort(d)
        ranked[cid] = [members[i] for i in order]
    return ranked


# --------------------------------------------------------------------------
# Emission: stateful round-robin
# --------------------------------------------------------------------------

class RoundRobinSelector:
    """Stateful round-robin across the cluster order.

    QUIRK, REPRODUCED DELIBERATELY: one call performs AT MOST ONE full pass over
    the clusters. The reference uses a `for ... else` whose `else` breaks the
    outer loop whenever a complete pass finishes without reaching the requested
    count. So a single call asking for more than len(cluster_order) inputs
    returns at most one per cluster, and the caller must ask again.

    The research driver hides this by requesting small increments and tracking
    `last_budget_size = len(previously_selected)`, so the shortfall is carried
    into the next budget. `drive_budgets` below reproduces that loop.
    """

    def __init__(self, cluster_order: Sequence[Any], input_ranking: Mapping[Any, list[InputId]]):
        self.cluster_order = list(cluster_order)
        self.input_ranking = input_ranking
        self.cluster_ptr = 0
        self.input_pointers = {cid: 0 for cid in self.cluster_order}

    def select(self, previously_selected: set, needed_inputs: int) -> list[InputId]:
        new_inputs: list[InputId] = []
        K = len(self.cluster_order)
        if K == 0:
            return []

        while len(new_inputs) < needed_inputs:
            for _ in range(K):
                cid = self.cluster_order[self.cluster_ptr]
                ranked = self.input_ranking.get(cid, [])
                ip = self.input_pointers[cid]
                while ip < len(ranked):
                    inp = ranked[ip]
                    ip += 1
                    self.input_pointers[cid] = ip
                    if inp not in previously_selected and inp not in new_inputs:
                        new_inputs.append(inp)
                        break
                self.cluster_ptr = (self.cluster_ptr + 1) % K
                if len(new_inputs) >= needed_inputs:
                    break
            else:
                break  # a full pass did not reach the target -- give up for now
        return new_inputs


def drive_budgets(
    cluster_order: Sequence[Any],
    input_ranking: Mapping[Any, list[InputId]],
    budgets: Sequence[int],
) -> tuple[list[InputId], dict[int, list[InputId]]]:
    """Reproduce run_deterministic_strategies' budget loop.

    Returns the cumulative ordering and a snapshot per budget. Note the snapshot
    at budget B can contain FEWER than B inputs, because of the one-pass quirk;
    the shortfall is carried forward via `last_budget_size`.
    """
    selector = RoundRobinSelector(cluster_order, input_ranking)
    previously_selected: set = set()
    ordered: list[InputId] = []
    snapshots: dict[int, list[InputId]] = {}
    last_budget_size = 0

    for budget in budgets:
        needed = budget - last_budget_size
        new_inputs = selector.select(previously_selected, needed)
        for inp in new_inputs:
            if inp not in previously_selected:
                ordered.append(inp)
        previously_selected.update(new_inputs)
        last_budget_size = len(previously_selected)
        snapshots[budget] = list(ordered)

    return ordered, snapshots


def full_ordering(
    cluster_order: Sequence[Any],
    input_ranking: Mapping[Any, list[InputId]],
    total: int,
) -> list[InputId]:
    """The complete prioritized ordering.

    Defined as the limit of the reference process driven one input at a time,
    which is what a budget sequence of 1,2,3,... produces. `tests/golden/`
    asserts this equals the reference's cumulative output.
    """
    return drive_budgets(cluster_order, input_ranking, list(range(1, total + 1)))[0]


# --------------------------------------------------------------------------
# Cluster Coverage and generator selection
# --------------------------------------------------------------------------

def k_effective(labels: np.ndarray) -> int:
    """K_eff excludes the noise label -1; if everything is noise, count it."""
    labels = np.asarray(labels)
    without_noise = np.unique(labels[labels != -1])
    return int(without_noise.size) if without_noise.size > 0 else int(np.unique(labels).size)


def cluster_coverage(
    id_to_label: Mapping[InputId, Any],
    id_to_generator: Mapping[InputId, str],
    generator_order: Sequence[str],
    k_eff: int,
) -> dict[str, float]:
    """CC(g) = |distinct clusters containing an input from g| / max(1, K_eff).

    QUIRK, REPRODUCED: the reference does NOT exclude the noise label -1 from
    the per-generator set, although it does exclude it from K_eff. With Affinity
    Propagation -- the published configuration -- no point is labelled -1, so
    this is unobservable there; it matters for OPTICS/HDBSCAN.

    Generators in `generator_order` with no inputs score 0.0. A generator
    present in the data but absent from `generator_order` raises, matching the
    reference's KeyError rather than silently dropping it.
    """
    touched: dict[str, set] = {g: set() for g in generator_order}
    for input_id, label in id_to_label.items():
        touched[id_to_generator[input_id]].add(label)
    return {g: len(c) / max(1, k_eff) for g, c in touched.items()}


def competition_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Rank descending with ties taking the best rank -- pandas'
    `rank(ascending=False, method="min")`, without the pandas dependency.

    Example: values 0.9, 0.8, 0.8, 0.5 -> ranks 1, 2, 2, 4.
    """
    ordered = sorted(values.items(), key=lambda kv: -kv[1])
    ranks: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        best = float(i + 1)  # method="min": every tied element gets the first rank
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = best
        i = j + 1
    return ranks


def ranksum_select(
    per_run_coverage: Sequence[Mapping[str, float]],
    candidate_tools: Sequence[str],
) -> tuple[dict[str, float], str]:
    """Rank generators per run by CC (descending), sum the ranks, lowest wins.

    Mirrors compute_ranksum_all_models: ties take the best rank, and the winner
    is pandas' `idxmin`, which on a tie takes the first in index order. Index
    order there is the per-run sorted order, so it is reproduced by ordering the
    accumulator the same way.
    """
    if not per_run_coverage:
        raise ValueError("ranksum_select needs at least one run's coverage table.")

    ranksum: dict[str, float] = {}
    order: list[str] = []
    for coverage in per_run_coverage:
        available = [t for t in candidate_tools if t in coverage]
        if not available:
            raise ValueError(
                f"None of the candidate generators {list(candidate_tools)} appear in this run's "
                f"coverage table (found {sorted(coverage)})."
            )
        values = {t: coverage[t] for t in available}
        # pandas builds the frame from the descending-sorted series, so the row
        # index -- and therefore idxmin's tie-break -- follows the FIRST run.
        for name, _ in sorted(values.items(), key=lambda kv: -kv[1]):
            if name not in ranksum:
                ranksum[name] = 0.0
                order.append(name)
        for name, rank in competition_ranks(values).items():
            ranksum[name] += rank

    winner = min(order, key=lambda name: ranksum[name])
    return ranksum, winner
