"""Generator selection by Cluster Coverage: keep the top generators, execute only their inputs."""
import json
import sys
from types import SimpleNamespace

import pytest
import yaml

from spreadex.core import selection, sources
from spreadex.core.campaign import Campaign
from spreadex.core.config import ConfigError, load_config
from spreadex.core.sources import GeneratedInput


def _item(h, g):
    return SimpleNamespace(blob_hash=h, generator=g)


def test_choose_keeps_the_highest_cc_and_breaks_ties_by_name():
    scores = {"a": 0.5, "b": 0.8, "c": 0.5, "corpus": 0.9}
    # only configured generators compete; the project's own corpus is never a candidate
    assert selection.choose(scores, ["a", "b", "c"], 2) == (["b", "a"], ["c"])
    assert selection.choose(scores, ["a", "b"], 2) is None, "nothing to choose from"
    assert selection.choose(scores, ["a", "b", "missing"], 1) == (["b"], ["a"])


def test_apply_keeps_order_seeds_and_shared_inputs():
    ordered = [_item("1", "a"), _item("2", "c"), _item("3", "corpus"), _item("4", "c"), _item("5", "a")]
    origins = {"1": {"a"}, "2": {"c"}, "3": {"corpus"}, "4": {"c", "b"}, "5": {"a"}}
    kept = selection.apply(ordered, origins, dropped=["c"])
    # "2" only came from the dropped generator; "4" was also produced by a kept one
    assert [i.blob_hash for i in kept] == ["1", "3", "4", "5"]


def _project(tmp_path, extra):
    (tmp_path / "sut.py").write_text("import sys\nt = open(sys.argv[1]).read()\nsys.exit(1 if 'boom' in t else 0)\n")
    cfg = {"sut": {"command": [sys.executable, "sut.py"], "cwd": ".", "timeout": "5s"},
           "oracle": {"type": "crash", "expected_exit_codes": [0]},
           "generators": ["wide", "mid", "narrow"],
           "budget": {"generation": "5s", "execution": "60s"}, **extra}
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump(cfg))
    return load_config(tmp_path / "spreadex.yaml")


# Three fake generators with clearly different diversity: "wide" writes many different kinds of
# input, "narrow" the same shape over and over.
_POOL = (
    [GeneratedInput(f"{w} {i}".encode(), "wide", 1.0)
     for i, w in enumerate(["alpha", "(beta)", "gamma+", "[delta]", "eps;", "zeta=", "boom!", "{eta}"])]
    + [GeneratedInput(f"mid {w}{i}".encode(), "mid", 1.0) for i, w in enumerate(["x", "y", "z", "x", "y"])]
    + [GeneratedInput(f"aaaa{i}".encode(), "narrow", 1.0) for i in range(8)]
)


@pytest.fixture
def fake_generation(monkeypatch):
    monkeypatch.setattr(sources, "collect", lambda *a, **k: list(_POOL))


def test_a_campaign_keeps_the_top_generators_and_records_why(tmp_path, fake_generation):
    cfg = _project(tmp_path, {"selection": {"by": "cc", "keep": 2}})
    lines = []
    r = Campaign(cfg, log=lines.append).run()
    sel = r.selection
    assert sel and len(sel["selected"]) == 2 and len(sel["dropped"]) == 1
    scores = sel["scores"]
    assert min(scores[g] for g in sel["selected"]) >= scores[sel["dropped"][0]]
    assert r.executed == sel["kept_inputs"] == len(_POOL) - sel["dropped_inputs"]
    assert any(l.startswith("  selected by cluster coverage:") for l in lines)
    manifest = json.loads((r.run_dir / "manifest.json").read_text())
    assert manifest["corpus"]["selection"]["selected"] == sel["selected"]


def test_without_selection_every_generator_is_executed(tmp_path, fake_generation):
    cfg = _project(tmp_path, {})
    r = Campaign(cfg, log=lambda *_: None).run()
    assert r.selection is None and r.executed == len(_POOL)


def test_selection_is_skipped_when_there_is_nothing_to_choose(tmp_path, fake_generation):
    cfg = _project(tmp_path, {"selection": {"keep": 3}})
    lines = []
    r = Campaign(cfg, log=lines.append).run()
    assert r.selection is None and r.executed == len(_POOL)
    assert any("every input is kept" in l for l in lines)


@pytest.mark.parametrize("bad", [{"by": "kpath", "keep": 2}, {"keep": 0}, {"keep": "two"}, {"keep": 2, "top": 1}, "cc"])
def test_bad_selection_is_a_config_error(tmp_path, bad):
    with pytest.raises(ConfigError):
        _project(tmp_path, {"selection": bad})


def test_selection_is_part_of_the_campaign_identity(tmp_path):
    a = _project(tmp_path, {}).hash()
    b = _project(tmp_path, {"selection": {"keep": 2}}).hash()
    assert a != b


def test_keep_all_is_explicit_and_keeps_every_generator(tmp_path, fake_generation):
    cfg = _project(tmp_path, {"selection": {"by": "cc", "keep": "all"}})
    assert cfg.selection == {"by": "cc", "keep": "all"}
    r = Campaign(cfg, log=lambda *_: None).run()
    assert r.selection is None and r.executed == len(_POOL)


def test_selection_needs_cc_scores_and_is_skipped_under_random_order(tmp_path, fake_generation):
    cfg = _project(tmp_path, {"selection": {"keep": 1}, "selection_signal": "random"})
    lines = []
    r = Campaign(cfg, log=lines.append).run()
    assert r.selection is None and r.executed == len(_POOL)
    assert any("needs the cc signal" in l for l in lines)
