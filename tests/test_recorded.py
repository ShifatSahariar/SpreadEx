"""Recordings: any generator's inputs, saved with provenance and replayed without regenerating."""
import json
import sys

import pytest

from spreadex.core.config import load_config
from spreadex.core.sources import GenerationStats, collect, recorded_sources
from spreadex.generators import GeneratorError
from spreadex.generators.recorded import load, write

INPUTS = [b"print(1);\n", b"var x = 2;\n", b"throw 3;\n"]


def test_a_recording_round_trips_with_its_provenance(tmp_path):
    write(tmp_path / "rec", "fandango", INPUTS, {"model": "none", "note": "test"}, suffix=".js")
    rec = load(tmp_path / "rec", "fandango")
    assert rec.inputs == INPUTS and rec.available == 3 and rec.provenance["note"] == "test"
    assert load(tmp_path / "rec", "fandango", 2).inputs == INPUTS[:2], "first N, in recorded order"
    assert rec.recording_sha256 == load(tmp_path / "rec", "fandango").recording_sha256


def test_an_altered_input_is_refused_not_used(tmp_path):
    write(tmp_path / "rec", "g", INPUTS, {})
    f = sorted((tmp_path / "rec" / "inputs").iterdir())[1]
    f.write_bytes(f.read_bytes() + b" ")
    with pytest.raises(GeneratorError, match="does not match its checksum"):
        load(tmp_path / "rec", "g")


@pytest.mark.parametrize("break_it,message", [
    (lambda d: (d / "manifest.json").unlink(), "no recording"),
    (lambda d: sorted((d / "inputs").iterdir())[0].unlink(), "is missing"),
    (lambda d: (d / "manifest.json").write_text("{"), "not valid JSON"),
])
def test_a_broken_recording_says_what_is_wrong(tmp_path, break_it, message):
    write(tmp_path / "rec", "g", INPUTS, {})
    break_it(tmp_path / "rec")
    with pytest.raises(GeneratorError, match=message):
        load(tmp_path / "rec", "g")


def test_a_recording_is_only_replayed_as_the_generator_that_made_it(tmp_path):
    write(tmp_path / "rec", "fuzz4all", INPUTS, {})
    with pytest.raises(GeneratorError, match="was made by 'fuzz4all'"):
        load(tmp_path / "rec", "fandango")


def test_an_entry_cannot_point_outside_the_recording(tmp_path):
    write(tmp_path / "rec", "g", INPUTS, {})
    man = json.loads((tmp_path / "rec" / "manifest.json").read_text())
    man["inputs"][0]["file"] = "../../etc/passwd"
    (tmp_path / "rec" / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(GeneratorError, match="outside"):
        load(tmp_path / "rec", "g")


def test_a_recording_is_never_written_over(tmp_path):
    write(tmp_path / "rec", "g", INPUTS, {})
    with pytest.raises(GeneratorError, match="already holds a recording"):
        write(tmp_path / "rec", "g", INPUTS, {})


def _project(tmp_path, generation: str, generators="[fuzz4all]"):
    (tmp_path / "spreadex.yaml").write_text(
        f'sut: {{command: ["{sys.executable}", "-c", "pass", "{{input}}"]}}\noracle: {{type: crash}}\n'
        f"generators: {generators}\ngeneration: {generation}\nseed: 1\n")
    return load_config(tmp_path / "spreadex.yaml")


class NoInstalls:
    """A generator manager that fails the test if anything asks it to install or run."""

    def ensure(self, ids, **kw):
        assert not ids, f"a replay must not need {ids} installed"


def test_replayed_inputs_are_attributed_to_their_generator_and_labelled(tmp_path):
    write(tmp_path / "rec", "fuzz4all", INPUTS, {"model": "gpt-4.1-mini"})
    cfg = _project(tmp_path, "{count: 2, fuzz4all: {mode: recorded, corpus: rec}}")
    stats: list[GenerationStats] = []
    got = collect(cfg, 60, log=lambda *_: None, manager=NoInstalls(), stats=stats)
    assert [g.data for g in got] == INPUTS[:2] and {g.generator for g in got} == {"fuzz4all"}
    d = stats[0].as_dict()
    assert d["source"] == "recorded" and d["produced"] == 2 and d["requested_count"] == 2
    assert d["recording"]["available"] == 3 and d["recording"]["provenance"]["model"] == "gpt-4.1-mini"


def test_there_is_no_fallback_between_recorded_and_live(tmp_path):
    cfg = _project(tmp_path, "{fuzz4all: {mode: recorded, corpus: missing}}")
    with pytest.raises(GeneratorError, match="no recording"):
        collect(cfg, 60, log=lambda *_: None, manager=NoInstalls())
    cfg = _project(tmp_path, "{fuzz4all: {mode: recorded}}")
    with pytest.raises(GeneratorError, match="needs `corpus"):
        recorded_sources(cfg)
    cfg = _project(tmp_path, "{fuzz4all: {mode: sometimes}}")
    with pytest.raises(GeneratorError, match="expected recorded or live"):
        recorded_sources(cfg)


def test_live_fuzz4all_is_refused_with_its_reason_rather_than_replayed(tmp_path):
    from spreadex.generators import GeneratorManager

    write(tmp_path / "rec", "fuzz4all", INPUTS, {})
    cfg = _project(tmp_path, "{fuzz4all: {mode: live}}")
    with pytest.raises(GeneratorError, match="live Fuzz4All generation is not available"):
        collect(cfg, 60, log=lambda *_: None, manager=GeneratorManager(cache_dir=tmp_path / "c"))


def test_a_runs_inputs_can_be_recorded_and_replayed_without_regenerating(tmp_path, monkeypatch, capsys):
    """Any generator's output from a past run becomes a recording; replaying it gives the same bytes."""
    import yaml as _yaml

    from spreadex.cli.main import main
    from spreadex.core.campaign import Campaign

    write(tmp_path / "rec", "fandango", INPUTS, {"note": "seeded"})
    cfg = _project(tmp_path, "{count: 3, fandango: {mode: recorded, corpus: rec}}", generators="[fandango]")
    result = Campaign(cfg, log=lambda *_: None).run()
    listing = (result.run_dir / "inputs.jsonl").read_text().splitlines()
    assert [json.loads(line)["generator"] for line in listing] == ["fandango"] * 3

    monkeypatch.chdir(tmp_path)
    assert main(["record", result.run_id, "fandango", "-o", "again"]) == 0
    again = load(tmp_path / "again", "fandango")
    assert again.inputs == INPUTS and again.provenance["source"] == f"SpreadEx run {result.run_id}"
    assert again.provenance["generation"]["source"] == "recorded", "the chain of replays is kept"

    raw = _yaml.safe_load((tmp_path / "spreadex.yaml").read_text())
    raw["generation"]["fandango"]["corpus"] = "again"
    (tmp_path / "spreadex.yaml").write_text(_yaml.safe_dump(raw))
    second = Campaign(load_config(tmp_path / "spreadex.yaml"), log=lambda *_: None).run()
    assert (second.run_dir / "inputs.jsonl").read_text() == (result.run_dir / "inputs.jsonl").read_text()
