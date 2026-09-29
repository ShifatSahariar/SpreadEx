"""Fixtures for the golden equivalence suite."""

from __future__ import annotations

import numpy as np
import pytest

from _research import RESEARCH_ROOT, ensure_on_path


@pytest.fixture(scope="session", autouse=True)
def _research_on_path():
    ensure_on_path()
    yield


# Each research function is imported independently. A single heavy optional
# dependency (hdbscan, pandas) must not be able to skip the whole gate.
_RESEARCH_FUNCS = {
    "cluster_by_centroid_spread":
        ("PRIORATIZATION.input_selection.cluster_strategies.by_centroid_spread",
         "cluster_by_centroid_spread"),
    "inputs_by_exemplar_distance":
        ("PRIORATIZATION.input_selection.input_strategies.by_exemplar_distance",
         "inputs_by_exemplar_distance"),
    "create_round_robin_cluster_selector":
        ("PRIORATIZATION.prioritization_utils.run_approaches_combo",
         "create_round_robin_cluster_selector"),
    "perform_clustering":
        ("FUZZ_TOOL_SELECTION.utils.clustering_analysis_utils", "perform_clustering"),
    "compute_ranksum_all_models":
        ("PRIORATIZATION.prioritization_utils.tool_selection_ranksum",
         "compute_ranksum_all_models"),
}


class _Research:
    """Lazy accessor for the research implementations."""

    def __getitem__(self, name):
        module_path, attr = _RESEARCH_FUNCS[name]
        ensure_on_path()
        import importlib
        try:
            return getattr(importlib.import_module(module_path), attr)
        except ImportError as exc:
            pytest.skip(
                f"cannot import {attr} from the research repository ({exc}).\n"
                f"  Fix: pip install -e '.[golden]' (and `pip install hdbscan` if that failed)."
            )


@pytest.fixture(scope="session")
def research():
    """The real research implementations, imported from the research repository."""
    if RESEARCH_ROOT is None:
        pytest.skip("research repository not found")
    return _Research()


@pytest.fixture
def corpus():
    """A fixed synthetic corpus: deterministic, and no embedding model needed.

    Generators with deliberately different footprints, plus equal-sized groups
    so the tie-breaking paths are actually exercised rather than merely present.
    """
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
