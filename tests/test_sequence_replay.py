"""Prioritization provenance, recorded-sequence replay, and campaigns recorded before variants.

Campaign tests use the toy-parser example (corpus only, a Python parser): no generator, no real SUT.
The legacy tests read the exported Rhino and JavaBASIC campaigns kept with the paper's artifact
(tests/fixtures/legacy) and never execute either system.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.core.replay import (config_from_manifest, manifest_from_export, recorded_prioritization,
                                  recorded_sequence, replay, sequence_from_export)
from spreadex.corpus import CorpusStore

ROOT = Path(__file__).resolve().parents[1]
LEGACY = Path(__file__).parent / "fixtures" / "legacy"


def _project(tmp_path, variant: str | None = None) -> Path:
    project = tmp_path / "toy"
    shutil.copytree(ROOT / "examples" / "toy-parser", project,
                    ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    if variant:
        y = yaml.safe_load((project / "spreadex.yaml").read_text())
        y["prioritization"] = {"variant": variant}
        (project / "spreadex.yaml").write_text(yaml.safe_dump(y, sort_keys=False))
    return project


def _executed(state_dir, run_id):
    with CorpusStore(state_dir) as store:
        return recorded_sequence(store, run_id)


# ------------------------------------------------------------ provenance

@pytest.mark.parametrize("variant", ["published", "replication"])
def test_a_campaign_records_how_it_was_ordered(tmp_path, variant):
    project = _project(tmp_path, variant if variant != "published" else None)
    cfg = load_config(project / "spreadex.yaml")
    result = Campaign(cfg, log=lambda *_: None).run()
    prov = json.loads((result.run_dir / "prioritization.json").read_text())
    manifest = json.loads((result.run_dir / "manifest.json").read_text())

    assert prov["variant"] == variant == manifest["corpus"]["prioritization"]["variant"]
    assert manifest["corpus"]["prioritization"]["provenance_file"] == "prioritization.json"
    members = [h for m in prov["clusters"].values() for h in m]
    assert sorted(prov["sequence"]) == sorted(members) and len(set(members)) == len(members)
    assert set(prov["cluster_order"]) == set(prov["clusters"])
    assert all(prov["exemplars"][c] in prov["clusters"][c] for c in prov["clusters"])
    # What was executed is the recorded execution order, in that order.
    assert _executed(cfg.state_dir, result.run_id) == prov["execution_order"][:result.executed]
    if variant == "published":
        assert prov["within_cluster"].startswith("farthest first")
    else:
        assert prov["within_cluster"].startswith("closest first") and "Affinity" in prov["exemplar"]


def test_the_export_carries_the_ordering(tmp_path):
    from spreadex.core.export import build_export

    project = _project(tmp_path)
    cfg = load_config(project / "spreadex.yaml")
    result = Campaign(cfg, log=lambda *_: None).run()
    _, out = build_export(cfg, result.run_id, tmp_path / "x.zip")
    with zipfile.ZipFile(out) as z:
        prov = json.loads(z.read("run/prioritization.json"))
        manifest = json.loads(z.read("run/manifest.json"))
    assert prov["variant"] == "published" and manifest["corpus"]["prioritization"]["variant"] == "published"


def test_the_ordering_is_deterministic(tmp_path):
    seqs = []
    for i in range(2):
        project = _project(tmp_path / str(i))
        result = Campaign(load_config(project / "spreadex.yaml"), log=lambda *_: None).run()
        seqs.append(json.loads((result.run_dir / "prioritization.json").read_text())["sequence"])
    assert seqs[0] == seqs[1]


# ---------------------------------------------------------------- replay

def _digest(run_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(run_dir.rglob("*")):
        if p.is_file():
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


def test_replay_executes_the_recorded_sequence_as_a_new_run(tmp_path):
    project = _project(tmp_path)
    cfg = load_config(project / "spreadex.yaml")
    source = Campaign(cfg, log=lambda *_: None).run()
    before = _digest(source.run_dir)

    out = replay(cfg.project_root, cfg.state_dir, source.run_id, log=lambda *_: None)

    assert out["run_id"] != source.run_id and out["replay_of"] == source.run_id
    assert _executed(cfg.state_dir, out["run_id"]) == _executed(cfg.state_dir, source.run_id)
    assert out["same_verdict"] == out["executed"] == source.executed and out["different_count"] == 0
    assert _digest(source.run_dir) == before                     # the source run is untouched
    m = json.loads((cfg.state_dir / "runs" / out["run_id"] / "manifest.json").read_text())
    assert m["corpus"]["replay"]["ordering"] == "recorded"
    assert m["corpus"]["prioritization"]["variant"] == "published"   # the SOURCE's ordering, as recorded


def test_replay_does_not_use_the_current_prioritization(tmp_path):
    """Switching the project to the other variant changes what a NEW campaign does, never what a
    replay of an old one executes."""
    project = _project(tmp_path)
    cfg = load_config(project / "spreadex.yaml")
    source = Campaign(cfg, log=lambda *_: None).run()
    y = yaml.safe_load((project / "spreadex.yaml").read_text())
    y["prioritization"] = {"variant": "replication"}
    (project / "spreadex.yaml").write_text(yaml.safe_dump(y, sort_keys=False))
    out = replay(cfg.project_root, cfg.state_dir, source.run_id, log=lambda *_: None)
    assert _executed(cfg.state_dir, out["run_id"]) == _executed(cfg.state_dir, source.run_id)


def test_the_cli_replays_by_default_and_regenerates_only_when_asked(tmp_path, monkeypatch, capsys):
    from spreadex.cli.main import main

    project = _project(tmp_path)
    cfg = load_config(project / "spreadex.yaml")
    source = Campaign(cfg, log=lambda *_: None).run()
    monkeypatch.chdir(project)
    assert main(["replay", source.run_id]) == 0
    text = capsys.readouterr().out
    assert "--execute" in text and "--regenerate" in text and "ordering     published" in text
    assert main(["replay", source.run_id, "--execute"]) == 0
    assert "reproduced their recorded verdict" in capsys.readouterr().out


# ----------------------------------------------- campaigns recorded before variants

@pytest.mark.parametrize("name, executed, env", [
    ("rhino-2026-10-16.zip", 236, {"RHINO_JAR": "/nonexistent/rhino.jar"}),
    ("javabasic-2026-10-16.zip", 600, {"BASIC_CLASSES": "/nonexistent/javabasic.jar"}),
])
def test_historical_campaigns_load_and_replay_their_recorded_sequence(tmp_path, monkeypatch, name, executed, env):
    """The paper's Rhino and JavaBASIC campaigns: their manifests load, their ordering is reported
    as unknown (they predate the variants and recorded none), their recorded sequence is rebuilt
    from the export, and a replay configuration is built from their manifest -- all without running
    either system."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    zip_path = LEGACY / name
    manifest = manifest_from_export(zip_path)
    assert recorded_prioritization(manifest) == {"variant": "unknown"}

    sequence = sequence_from_export(zip_path)
    assert len(sequence) == len(set(sequence)) == executed == manifest["results"]["executed"]

    (tmp_path / "proj").mkdir()
    cfg = config_from_manifest(tmp_path / "proj", manifest)
    assert [t.command[0] for t in cfg.targets] == ["java"]
    assert cfg.oracle == manifest["config"]["oracle"]
    # Regenerating would use today's default; replay never prioritizes, so it cannot relabel.
    assert cfg.prioritization == {"variant": "published"}
    assert "prioritization" not in (manifest.get("corpus") or {})
