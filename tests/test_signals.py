import pytest

from spreadex.signals import Item, make_signal


def corpus(n=60):
    items = []
    for i in range(n // 3):
        items.append(Item(f"a{i}", f"let x = {i} + 1;", "genA"))
        items.append(Item(f"b{i}", f"function f{i}() {{ return {i}; }}", "genB"))
        items.append(Item(f"c{i}", f"while (x < {i}) x++;", "genC"))
    return items


def test_ordering_is_a_complete_permutation():
    items = corpus()
    o = make_signal("cc").rank(items)
    assert sorted(o.order) == list(range(len(items))), "every input must be reachable"


def test_ordering_is_deterministic():
    items = corpus()
    s = make_signal("cc")
    assert s.rank(items, seed=42).order == s.rank(items, seed=42).order


def test_cluster_coverage_scores_every_generator():
    items = corpus()
    o = make_signal("cc").rank(items)
    assert set(o.generator_scores) == {"genA", "genB", "genC"}
    assert all(0.0 <= v <= 1.0 for v in o.generator_scores.values())


def test_ordering_spreads_across_generators_early():
    """The point of the diversity map: do not spend the first slice of budget
    on one generator."""
    items = corpus(90)
    o = make_signal("cc").rank(items)
    first = {items[i].generator for i in o.order[:12]}
    assert len(first) >= 2


def test_random_signal_is_seeded():
    items = corpus()
    assert make_signal("random").rank(items, seed=1).order == make_signal("random").rank(items, seed=1).order
    assert make_signal("random").rank(items, seed=1).order != make_signal("random").rank(items, seed=2).order


@pytest.mark.parametrize("n", [0, 1, 2])
def test_degenerate_corpora(n):
    items = [Item(f"h{i}", f"x{i}", "g") for i in range(n)]
    o = make_signal("cc").rank(items)
    assert sorted(o.order) == list(range(n))


def test_kpath_is_declared_not_silently_ignored():
    with pytest.raises(ValueError, match="not implemented"):
        make_signal("kpath")


def test_unknown_signal_is_rejected():
    with pytest.raises(ValueError):
        make_signal("vibes")


# ------------------------------------------- honesty about the clustering

def test_a_non_converging_clustering_is_reported_not_swallowed():
    """Affinity Propagation can fail to converge, and sklearn says so in a
    warning that reaches the user as a stack trace from a file they have never
    heard of -- or, worse, gets suppressed and leaves confident-looking CC
    values with nothing to qualify them."""
    import warnings

    import numpy as np
    from sklearn.exceptions import ConvergenceWarning

    from spreadex.signals.base import ClusterCoverageSignal, Item

    # Many near-identical inputs: the case AP struggles with in practice, and
    # the one a user hits when a generator keeps emitting the same shape.
    rng = np.random.default_rng(7)
    items = [Item(blob_hash=f"h{i:04d}", text=f"x = {rng.integers(0, 2)}",
                  generator="g" + str(i % 2))
             for i in range(120)]

    signal = ClusterCoverageSignal(embedding_model="tfidf", random_state=1)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        # Must not escape: the signal catches it and speaks for itself.
        ordering = signal.rank(items)

    assert ordering.order, "a shaky clustering still yields a usable ordering"
    assert len(ordering.order) == len(items), "every input still gets a position"
    # Unconditional: this corpus does not converge, and a test that shrugged
    # when the caveat was missing would pass just as happily if the reporting
    # were deleted.
    assert ordering.caveats, "non-convergence must produce a caveat"
    text = " ".join(ordering.caveats)
    assert "converge" in text
    assert "still a valid ordering" in text, "say what is and is not affected"


def test_a_healthy_corpus_reports_no_caveat():
    """A caveat on every run would be noise, and noise is ignored."""
    import numpy as np

    from spreadex.signals.base import ClusterCoverageSignal, Item

    rng = np.random.default_rng(11)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    items = [Item(blob_hash=f"h{i:04d}", text=" ".join(rng.choice(words, size=6)),
                  generator="g" + str(i % 3))
             for i in range(60)]
    ordering = ClusterCoverageSignal(embedding_model="tfidf", random_state=3).rank(items)
    assert ordering.caveats == []


def test_the_caveat_reaches_the_manifest(tmp_path):
    """A warning the campaign prints once and forgets is not evidence; a
    replay has to see it too."""
    from spreadex.core.campaign import CampaignResult

    result = CampaignResult(run_id="r", run_dir=tmp_path)
    assert result.signal_caveats == []
    result.signal_caveats = ["something to know"]
    assert result.signal_caveats == ["something to know"]


# ------------------------------------------------- the O(n^2) memory ceiling

def test_the_memory_estimate_tracks_what_was_actually_measured():
    """scripts/scale_audit.py measured 2.5 GB at n=5000 and 6.3 GB at 10000.
    An estimate that drifts from that is worse than none, because it is used
    to refuse work.

    Checked only at the large end: below a few thousand the measurement is
    mostly interpreter and sklearn baseline rather than clustering, and the
    guard never fires there anyway.
    """
    from spreadex.signals.base import ClusterCoverageSignal as C

    for n, measured_gb in ((5000, 2.5), (10000, 6.3)):
        est = C.estimated_bytes(n) / 1024 ** 3
        assert 0.5 * measured_gb <= est <= 1.5 * measured_gb, (n, est, measured_gb)


def test_the_estimate_errs_high_rather_than_low():
    """Underestimating is the direction that takes the machine down."""
    from spreadex.signals.base import ClusterCoverageSignal as C

    assert C.estimated_bytes(10000) / 1024 ** 3 >= 6.3 * 0.95


def test_a_corpus_too_large_for_the_machine_is_refused_before_it_allocates(monkeypatch):
    """A campaign that OOMs loses every input it generated, so this has to be
    checked before the allocation rather than discovered during it."""
    from spreadex.signals.base import ClusterCoverageSignal

    signal = ClusterCoverageSignal(embedding_model="tfidf")
    monkeypatch.setattr(signal, "_physical_memory_bytes", lambda: 8 * 1024 ** 3)

    with pytest.raises(MemoryError) as exc:
        signal._memory_guard(50_000)
    message = str(exc.value)
    assert "50,000" in message and "8 GB" in message
    assert "max_inputs" in message, "a refusal has to name the lever"
    assert "random" in message, "...and the way to run anyway"


def test_a_large_but_survivable_corpus_warns_instead_of_refusing(monkeypatch):
    from spreadex.signals.base import ClusterCoverageSignal

    signal = ClusterCoverageSignal(embedding_model="tfidf")
    monkeypatch.setattr(signal, "_physical_memory_bytes", lambda: 36 * 1024 ** 3)
    caveats = signal._memory_guard(14_000)
    assert caveats and "square of the corpus" in caveats[0]


def test_an_ordinary_corpus_is_not_nagged(monkeypatch):
    from spreadex.signals.base import ClusterCoverageSignal

    signal = ClusterCoverageSignal(embedding_model="tfidf")
    monkeypatch.setattr(signal, "_physical_memory_bytes", lambda: 8 * 1024 ** 3)
    assert signal._memory_guard(1000) == []


def test_the_guard_stays_quiet_when_it_cannot_tell(monkeypatch):
    """An unknown machine is not a reason to refuse to work."""
    from spreadex.signals.base import ClusterCoverageSignal

    signal = ClusterCoverageSignal(embedding_model="tfidf")
    monkeypatch.setattr(signal, "_physical_memory_bytes", lambda: None)
    assert signal._memory_guard(10_000_000) == []


def test_the_default_time_cap_cannot_oom_a_small_laptop():
    """Four generators at the cap is the realistic pool, and it has to fit on a
    machine smaller than the one this was developed on."""
    from spreadex.core.sources import DEFAULT_TIME_MODE_CAP
    from spreadex.signals.base import ClusterCoverageSignal as C

    pooled = 4 * DEFAULT_TIME_MODE_CAP
    assert C.estimated_bytes(pooled) < 32 * 1024 ** 3, (
        f"{pooled} pooled inputs would need "
        f"{C.estimated_bytes(pooled) / 1024 ** 3:.0f} GB"
    )
