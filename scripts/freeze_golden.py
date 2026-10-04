"""Freeze the ICST 2026 research implementation's outputs on a public corpus.

Ordinary CI has no access to the research repository, so without this it can
only check that our code runs -- not that it computes the published algorithm.
These frozen outputs come from the research code itself and let any checkout
verify the numbers. The repository-backed audit in tests/golden/ still runs,
and is still what gates a release.

    SPREADEX_RESEARCH_REPO=/path/to/SpreadEx-2026/research \\
        python scripts/freeze_golden.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "golden"))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from _research import RESEARCH_ROOT, ensure_on_path  # noqa: E402

if RESEARCH_ROOT is None:
    raise SystemExit("set SPREADEX_RESEARCH_REPO to the research repository")
ensure_on_path()

# The ORDERINGS and CC below come from the RESEARCH implementation. Computing
# them with our own code would make the fixture circular: it would agree with
# us by construction and could never catch a drift, which is the one thing it
# exists to do.
#
# The clustering is the exception, and deliberately so. tests/golden/ already
# proves our cluster_once agrees with the research perform_clustering (same
# K_eff, same partition); both sides are then handed that one clustering so the
# comparison is of the ordering algorithms rather than of sklearn tie-breaking.
# This script follows the same protocol, for the same reason.
import importlib  # noqa: E402

from spreadex.prioritization import reference as ref  # noqa: E402

perform_clustering = importlib.import_module(
    "FUZZ_TOOL_SELECTION.utils.clustering_analysis_utils").perform_clustering
cluster_by_centroid_spread = importlib.import_module(
    "PRIORATIZATION.input_selection.cluster_strategies.by_centroid_spread"
).cluster_by_centroid_spread
inputs_by_exemplar_distance = importlib.import_module(
    "PRIORATIZATION.input_selection.input_strategies.by_exemplar_distance"
).inputs_by_exemplar_distance
create_round_robin_cluster_selector = importlib.import_module(
    "PRIORATIZATION.prioritization_utils.run_approaches_combo"
).create_round_robin_cluster_selector

OUT = ROOT / "tests" / "fixtures" / "golden" / "icst2026_reference.json"
SEED = 42


def fixed_corpus():
    """Byte-identical to the corpus fixture in tests/golden/conftest.py."""
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


def main() -> int:
    embeddings, generators = fixed_corpus()
    ids = list(embeddings)
    vectors = [embeddings[i] for i in ids]

    clusters, exemplars = ref.cluster_once(embeddings, random_state=SEED)
    id_to_label = {i: label for label, members in clusters.items() for i in members}

    # Cross-check against the research clustering before anything is frozen: if
    # these disagree, the fixture would be recording the wrong partition.
    their_labels, their_k_eff, _ = perform_clustering(
        vectors, ids, algo="Affinity", random_seed=SEED)
    k_eff = ref.k_effective(np.array([id_to_label[i] for i in ids]))
    assert k_eff == their_k_eff, (k_eff, their_k_eff)
    ours = {frozenset(m) for m in clusters.values()}
    theirs: dict = {}
    for name, label in their_labels.items():
        theirs.setdefault(label, []).append(name)
    assert ours == {frozenset(m) for m in theirs.values()}, "clusterings differ"

    # CC exactly as FUZZ_TOOL_SELECTION computes it: distinct clusters a
    # generator touches, over K_eff.
    cc = {}
    for gen in sorted(set(generators.values())):
        touched = {id_to_label[i] for i in ids if generators[i] == gen}
        cc[gen] = len(touched) / max(1, k_eff)

    cluster_order = cluster_by_centroid_spread(clusters, embeddings)
    ranking = inputs_by_exemplar_distance(clusters, embeddings, exemplars)
    # One call returns at most one input per cluster -- the published
    # selector makes a single pass. The full ordering is the limit of driving
    # it one input at a time, which is what tests/golden/ asserts too.
    selector = create_round_robin_cluster_selector(cluster_order, ranking)
    previously: set = set()
    order: list = []
    for budget in range(1, len(ids) + 1):
        new = selector(clusters=clusters, previously_selected=previously,
                       needed_inputs=budget - len(order), embeddings=embeddings)
        for inp in new:
            if inp not in previously:
                previously.add(inp)
                order.append(inp)
        if len(order) >= len(ids):
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "_what": "Outputs of the ICST 2026 research implementation on the corpus "
                 "in tests/golden/conftest.py. Regenerate only with "
                 "scripts/freeze_golden.py against the research repository.",
        "_research_root": str(RESEARCH_ROOT),
        "seed": SEED,
        "k_eff": int(k_eff),
        "cluster_sizes": sorted(len(v) for v in clusters.values()),
        "id_to_label": {k: int(v) for k, v in id_to_label.items()},
        "cluster_coverage": {g: float(v) for g, v in cc.items()},
        "cluster_order": [int(c) for c in cluster_order],
        "prioritized_order": list(order),
    }, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  k_eff={k_eff}  CC={cc}")
    print(f"  ordering of {len(order)} inputs, first 5: {order[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
