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
