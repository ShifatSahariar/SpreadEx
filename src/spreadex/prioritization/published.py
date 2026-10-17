"""SpreadEx prioritization as published: Algorithm 1 and Section IV-B of the ICST 2026 paper.

This module is the Workbench's default ordering (`prioritization.variant: published`). It is written
from the paper's text, not ported from the replication code, and it differs from that code in two
places, both of which the replication code is known to do differently (`reference.py` keeps the
replication behaviour, `variant: replication`):

* **Exemplar.** "the input whose embedding is closest to the cluster centroid" (Sec. IV-B, Alg. 1
  line 15). The paper names no metric for "closest"; we use Euclidean distance to the cluster's mean
  vector (our interpretation, consistent with the Euclidean ranking of Phase 2). The replication
  code uses Affinity Propagation's own exemplar instead.
* **Within-cluster order.** "ranked in descending order based on their Euclidean distance from the
  exemplar ... inputs that differ more from the exemplar get higher priority" (Alg. 1 lines 17-19).
  Here: farthest first. The replication code ranks closest first.

The ICST experimental results were produced by the replication code's ordering. This variant does
not reproduce them; it is evaluated on its own.

Unchanged from the replication code, because the paper says the same thing:

* **Centroids** are the mean of the cluster's embeddings (Alg. 1 lines 2-4).
* **First cluster** is the smallest. Among equally small clusters, the one whose centroid has the
  greatest average distance to *all other clusters* goes first. The paper's sentence ("the one with
  the highest average distance from the other clusters that have the same minimum size") is read as
  "among the clusters of minimum size, the most isolated one"; this reading was chosen explicitly
  and is the one the replication code implements. Remaining ties: the first such cluster in order of
  first appearance in the pool.
* **Later clusters**: max-min over centroid distances (Alg. 1 lines 7-11). The paper does not name
  the metric; cosine distance between centroids is used, as in the replication code.
* **Round-robin** emission over the ordered clusters (Alg. 1 lines 21-30).

Ties anywhere in Phase 2 (equal distances) go to the input that appears first in the pool, so the
ordering is deterministic for a fixed pool and clustering.
"""

from __future__ import annotations

from typing import Any, Hashable, Mapping, Sequence

import numpy as np

from . import reference as ref

InputId = Hashable


def _pool_rank(embeddings: Mapping[InputId, np.ndarray]) -> dict[InputId, int]:
    return {i: n for n, i in enumerate(embeddings)}


def exemplar_closest_to_centroid(clusters: Mapping[Any, list[InputId]],
                                 embeddings: Mapping[InputId, np.ndarray]) -> dict[Any, InputId]:
    """Alg. 1 line 15: the member whose embedding is closest (Euclidean) to the cluster centroid."""
    rank = _pool_rank(embeddings)
    out: dict[Any, InputId] = {}
    for cid, members in clusters.items():
        if not members:
            continue
        centroid = ref.compute_centroid(embeddings, members)
        out[cid] = min(members, key=lambda m: (float(np.linalg.norm(np.asarray(embeddings[m]) - centroid)),
                                               rank[m]))
    return out


def farthest_first_ranking(clusters: Mapping[Any, list[InputId]],
                           embeddings: Mapping[InputId, np.ndarray],
                           exemplars: Mapping[Any, InputId]) -> dict[Any, list[InputId]]:
    """Alg. 1 lines 16-18: members in descending Euclidean distance from the exemplar."""
    rank = _pool_rank(embeddings)
    ranked: dict[Any, list[InputId]] = {}
    for cid, members in clusters.items():
        ex = np.asarray(embeddings[exemplars[cid]]) if members else None
        ranked[cid] = sorted(members, key=lambda m: (-float(np.linalg.norm(np.asarray(embeddings[m]) - ex)),
                                                     rank[m]))
    return ranked


def cluster_order(clusters: Mapping[Any, list[InputId]],
                  embeddings: Mapping[InputId, np.ndarray]) -> list[Any]:
    """Alg. 1 lines 1-13 (see the module docstring for the tie rule).

    The clusters are presented in order of their first member's position in the pool, so a remaining
    tie goes to the cluster that appears first -- independent of how the clustering numbered them.
    """
    rank = _pool_rank(embeddings)
    ordered = dict(sorted(((cid, m) for cid, m in clusters.items() if m),
                          key=lambda kv: min(rank[i] for i in kv[1])))
    return ref.centroid_spread_order(ordered, embeddings)


#: What this variant does, recorded with every campaign that uses it.
RULES = {
    "variant": "published",
    "specification": "ICST 2026, Sec. IV-B and Algorithm 1",
    "centroid": "arithmetic mean of the member embeddings",
    "cluster_distance": "cosine, between centroids",
    "first_cluster": "smallest; among equally small, greatest mean distance to all other clusters",
    "cluster_order": "max-min: next is the cluster farthest from its nearest already chosen one",
    "exemplar": "member closest to the centroid (Euclidean: our interpretation, the paper names no metric)",
    "within_cluster": "farthest first (descending Euclidean distance from the exemplar)",
    "traversal": "round-robin, one input per cluster per round",
    "ties": "every remaining tie goes to the first in pool order",
}


def prioritize(clusters: Mapping[Any, list[InputId]],
               embeddings: Mapping[InputId, np.ndarray]) -> tuple[list[InputId], dict]:
    """The full published ordering of every input, plus what produced it (for the manifest)."""
    from . import prioritize as shared
    return shared("published", clusters, embeddings)
