"""PHASE 3 GATE (continued): Cluster Coverage and generator selection.

These compare against the REAL research pipeline functions, driven through
their own on-disk interfaces (vector files, per-run CSVs), so the comparison
covers file-name parsing and tool attribution as well as the arithmetic.
"""

from __future__ import annotations

import numpy as np
import pytest

from spreadex.prioritization import reference as ref

from _research import requires_research

pytestmark = requires_research

SEED = 42
GENERATORS = ["fan_con", "fuzz_equal", "isla_con"]


@pytest.fixture
def vector_dir(tmp_path, corpus):
    """Write the corpus as `<tool>_<id>_vector.txt`, the layout the research
    pipeline's load_all_vectors expects."""
    embeddings, _ = corpus
    d = tmp_path / "vectors"
    d.mkdir()
    mapping = {}
    for i, (key, vec) in enumerate(sorted(embeddings.items())):
        tool = GENERATORS[i % len(GENERATORS)]
        fname = f"{tool}_{i}_vector.txt"
        np.savetxt(d / fname, vec)
        mapping[fname] = (tool, vec)
    return d, mapping


def test_filename_to_generator_attribution_matches(vector_dir):
    """`fan_con_7_vector.txt` must attribute to `fan_con`, not `fan`."""
    from FUZZ_TOOL_SELECTION.utils.clustering_analysis_utils import load_all_vectors

    d, mapping = vector_dir
    _, ids, id2tool = load_all_vectors(str(d))
    for fname in ids:
        assert id2tool[fname] == mapping[fname][0]


def test_cluster_coverage_values_are_identical(vector_dir, research):
    """CC per generator, end to end through the research pipeline."""
    from FUZZ_TOOL_SELECTION.utils.clustering_analysis_utils import (
        cluster_coverage_pipeline,
        load_all_vectors,
    )

    d, _ = vector_dir
    rows, _ = cluster_coverage_pipeline(
        embedding_models={"TEST": str(d)},
        algorithms=["Affinity"],
        k_values=[],
        generator_order=GENERATORS,
        output_csv=None,
        random_seed=SEED,
    )
    assert len(rows) == 1
    their_row = rows[0]
    their_cc = {g: their_row[g] for g in GENERATORS}

    # Ours, from the same clustering.
    vecs, ids, id2tool = load_all_vectors(str(d))
    id2label, k_eff, _ = research["perform_clustering"](vecs, ids, algo="Affinity", random_seed=SEED)
    assert k_eff == their_row["K_eff"]
    our_cc = ref.cluster_coverage(id2label, id2tool, GENERATORS, k_eff)

    assert our_cc == pytest.approx(their_cc, rel=0, abs=0), "Cluster Coverage diverged"


def test_generator_with_no_inputs_scores_zero(research):
    """A generator listed but absent from the data must score 0.0, not vanish."""
    id2label = {"a": 0, "b": 1}
    id2gen = {"a": "fan_con", "b": "fan_con"}
    cc = ref.cluster_coverage(id2label, id2gen, ["fan_con", "isla_con"], k_eff=2)
    assert cc == {"fan_con": 1.0, "isla_con": 0.0}


def test_noise_label_is_counted_like_the_reference():
    """QUIRK: the reference counts the -1 noise label as a touched cluster while
    excluding it from K_eff. Pinned so any change is deliberate."""
    id2label = {"a": -1, "b": 0}
    id2gen = {"a": "g1", "b": "g2"}
    cc = ref.cluster_coverage(id2label, id2gen, ["g1", "g2"], k_eff=1)
    assert cc["g1"] == 1.0  # -1 counted as a cluster for g1


def test_unknown_generator_raises_like_the_reference():
    with pytest.raises(KeyError):
        ref.cluster_coverage({"a": 0}, {"a": "surprise"}, ["g1"], k_eff=1)


# ------------------------------------------------------- generator selection

def write_run_csvs(tmp_path, per_run_cc):
    """Lay out per-run coverage CSVs the way compute_ranksum_all_models reads them."""
    import pandas as pd

    base = tmp_path / "cc"
    base.mkdir()
    for i, cc in enumerate(per_run_cc, start=1):
        rd = base / f"run_{i}"
        rd.mkdir()
        row = {"Model": "TEST", "Cluster Algo": "Affinity", "K_eff": 10, **cc}
        pd.DataFrame([row]).to_csv(rd / f"cluster_coverage_summary_run_{i}.csv", index=False)
    return base


@pytest.mark.parametrize("per_run_cc", [
    # clear winner
    [{"fan_con": 0.9, "fuzz_equal": 0.5, "isla_con": 0.2}],
    # winner changes between runs
    [{"fan_con": 0.9, "fuzz_equal": 0.5, "isla_con": 0.2},
     {"fan_con": 0.3, "fuzz_equal": 0.8, "isla_con": 0.7},
     {"fan_con": 0.4, "fuzz_equal": 0.9, "isla_con": 0.6}],
    # exact ties -- the interesting case for method="min"
    [{"fan_con": 0.5, "fuzz_equal": 0.5, "isla_con": 0.2},
     {"fan_con": 0.5, "fuzz_equal": 0.5, "isla_con": 0.9}],
    # everything tied
    [{"fan_con": 0.4, "fuzz_equal": 0.4, "isla_con": 0.4}],
])
def test_ranksum_generator_selection_is_identical(tmp_path, research, per_run_cc):
    base = write_run_csvs(tmp_path, per_run_cc)
    ranksum_all, winners = research["compute_ranksum_all_models"](
        base_dir=str(base), candidate_tools=GENERATORS, save_dir=str(tmp_path / "out")
    )
    their_ranksum = ranksum_all["TEST"].to_dict()
    their_winner = winners.set_index("Model").loc["TEST", "BestTool"]

    our_ranksum, our_winner = ref.ranksum_select(per_run_cc, GENERATORS)

    assert our_ranksum == pytest.approx(their_ranksum)
    assert our_winner == their_winner, "generator selection diverged"


def test_competition_ranking_gives_ties_the_best_rank():
    ranks = ref.competition_ranks({"a": 0.9, "b": 0.8, "c": 0.8, "d": 0.5})
    assert ranks == {"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0}
