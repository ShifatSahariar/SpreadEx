"""SpreadEx prioritization: one entry point, two variants.

    published    Algorithm 1 as printed in the ICST 2026 paper (published.py). The default.
    replication  the ordering of the paper's replication code (reference.py), which produced its
                 results. The two differ only in the exemplar and the within-cluster direction;
                 centroids, the cluster order and round-robin emission are shared.

Neither variant claims bit-identical reproduction of the ICST experiments: the exact historical
command lines and source revision of every published result were not established.
"""

from __future__ import annotations

from typing import Any, Hashable, Mapping

import numpy as np

from . import published, reference
from .reference import (
    centroid_spread_order,
    cluster_coverage,
    cluster_once,
    drive_budgets,
    exemplar_distance_ranking,
    full_ordering,
    k_effective,
    ranksum_select,
)

VARIANTS = ("published", "replication")

#: What the replication variant does, recorded with every campaign that uses it.
REPLICATION_RULES = {
    "variant": "replication",
    "specification": "the ICST 2026 replication code (PRIORATIZATION/, SpreadEx_RR)",
    "centroid": "arithmetic mean of the member embeddings",
    "cluster_distance": "cosine, between centroids",
    "first_cluster": "smallest; among equally small, greatest mean distance to all other clusters",
    "cluster_order": "max-min: next is the cluster farthest from its nearest already chosen one",
    "exemplar": "Affinity Propagation's exemplar (cluster_centers_indices_)",
    "within_cluster": "closest first (ascending Euclidean distance from the exemplar)",
    "traversal": "round-robin, one input per cluster per round",
    "ties": "as the replication code: first cluster in clustering order; numpy argsort among "
            "equal distances (not guaranteed stable)",
}


def prioritize(variant: str, clusters: Mapping[Any, list[Hashable]],
               embeddings: Mapping[Hashable, np.ndarray],
               ap_exemplars: Mapping[Any, Hashable] | None = None) -> tuple[list[Hashable], dict]:
    """Order every input of a clustered pool. Returns (sequence, provenance).

    `embeddings` are the raw vectors, in pool order (Affinity Propagation clustered an L2-normalized
    copy, as the research code does; centroids and distances use the raw ones). `ap_exemplars` maps
    each cluster to Affinity Propagation's exemplar; only the replication variant uses it.
    """
    if variant == "published":
        order = published.cluster_order(clusters, embeddings)
        exemplars = published.exemplar_closest_to_centroid(clusters, embeddings)
        ranking = published.farthest_first_ranking(clusters, embeddings, exemplars)
        rules = published.RULES
    elif variant == "replication":
        if ap_exemplars is None:
            raise ValueError("the replication variant needs Affinity Propagation's exemplars")
        order = reference.centroid_spread_order(clusters, embeddings)
        exemplars = dict(ap_exemplars)
        ranking = reference.exemplar_distance_ranking(clusters, embeddings, exemplars, direction="closest")
        rules = REPLICATION_RULES
    else:
        raise ValueError(f"Unknown prioritization variant {variant!r}: {', '.join(VARIANTS)}")
    sequence = reference.full_ordering(order, ranking, len(embeddings))
    provenance = {**rules, "cluster_order": list(order),
                  "clusters": {c: list(m) for c, m in clusters.items()},
                  "exemplars": {c: exemplars[c] for c in clusters if c in exemplars},
                  "sequence": list(sequence)}
    return sequence, provenance


__all__ = [
    "prioritize", "VARIANTS", "REPLICATION_RULES", "published", "reference", "cluster_once",
    "centroid_spread_order", "exemplar_distance_ranking", "drive_budgets", "full_ordering",
    "cluster_coverage", "k_effective", "ranksum_select",
]
