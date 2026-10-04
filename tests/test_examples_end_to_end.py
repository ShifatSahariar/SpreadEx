"""End-to-end: the examples must behave exactly as their READMEs claim.

This is the regression test for the whole architecture -- generation, the
corpus store, the diversity map, execution, the oracle and the manifest all
have to work together for these numbers to come out right.
"""

import shutil
from pathlib import Path

import pytest

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def project(tmp_path):
    def _copy(name):
        dest = tmp_path / name
        shutil.copytree(EXAMPLES / name, dest,
                    ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
        return load_config(dest / "spreadex.yaml")
    return _copy


def test_toy_parser(project):
    cfg = project("toy-parser")
    r = Campaign(cfg, log=lambda *_: None).run(jobs=4)

    assert r.generated == 60
    assert r.valid == 60
    assert r.executed == 60
    # The claim that matters: correctly-rejected inputs are NOT bugs.
    assert r.verdicts.get("ok") == 40
    assert r.verdicts.get("expected_rejection") == 15
    assert r.verdicts.get("crash") == 5
    assert len(r.signatures) == 1
    assert len(r.new_signatures) == 1


def test_differential(project):
    cfg = project("differential")
    assert cfg.is_differential
    r = Campaign(cfg, log=lambda *_: None).run(jobs=4)

    assert r.executed == 60
    assert r.verdicts.get("ok") == 45
    # Differently-worded rejections are agreement, not divergence.
    assert r.verdicts.get("expected_rejection") == 10
    assert r.verdicts.get("divergence") == 5
    assert r.verdicts.get("crash", 0) == 0


def test_manifest_is_written_and_replayable(project):
    import json

    cfg = project("toy-parser")
    r = Campaign(cfg, log=lambda *_: None).run(jobs=4)
    m = json.loads((r.run_dir / "manifest.json").read_text())

    assert m["config_hash"] == cfg.hash()
    assert m["seed"] == cfg.seed
    assert m["targets"][0]["command"]
    assert m["effective"]["execution_s"] == cfg.budget.execution_s
    assert (r.run_dir / "results.jsonl").exists()


def test_a_replay_reproduces_the_same_verdicts(project):
    cfg = project("toy-parser")
    quiet = lambda *_: None
    first = Campaign(cfg, log=quiet).run(jobs=4)
    second = Campaign(cfg, log=quiet).run(jobs=4)

    assert first.verdicts == second.verdicts
    assert {s[0] for s in first.signatures} == {s[0] for s in second.signatures}
    # Signatures already seen are not reported as new -- the CI signal.
    assert second.new_signatures == []


def test_budget_stops_execution_early(project):
    cfg = project("toy-parser")
    cfg.budget.max_inputs = 10
    r = Campaign(cfg, log=lambda *_: None).run(jobs=4)
    assert r.executed == 10
    assert r.prioritized == 10
