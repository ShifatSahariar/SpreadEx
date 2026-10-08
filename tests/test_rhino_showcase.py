"""The Rhino example: a separate managed project, its provenance, and how Rhino's output is judged.

The execution tests run the real, pinned Rhino. They need Java and the verified jar
(`spreadex runtimes install rhino`, which CI does first) and say so when skipped.
"""
import hashlib
import re
import shutil
import sys
from pathlib import Path

import pytest

from spreadex import examples, runtimes
from spreadex.core.config import load_config
from spreadex.exec.observation import Observation
from spreadex.exec.oracle import Verdict, make_oracle
from spreadex.generators.recorded import load

SRC = examples.source_dir("rhino")


def test_the_example_ships_its_config_grammars_and_recording():
    for rel in ("spreadex.yaml", "README.md", "grammars/fandango/rhino.fan", "grammars/grammarinator/rhino.g4",
                "grammars/fuzz4all/documentation.md", "grammars/fuzz4all/example_code.js",
                "grammars/PROVENANCE.md", "recorded/fuzz4all/manifest.json"):
        assert (SRC / rel).is_file(), rel
    cfg = load_config(SRC / "spreadex.yaml")
    assert cfg.generators == ["fandango", "grammarinator", "fuzz4all"]
    assert cfg.raw["generation"]["count"] == 100 and cfg.raw["generation"]["fuzz4all"]["mode"] == "recorded"
    assert "${SPREADEX_RUNTIME_RHINO}" in cfg.targets[0].command


def test_every_copied_file_matches_its_recorded_checksum():
    rows = re.findall(r"\| `([^`]+)` \| `[^`]+` \| `([0-9a-f]{64})` \|", (SRC / "grammars/PROVENANCE.md").read_text())
    assert len(rows) == 4
    for rel, digest in rows:
        assert hashlib.sha256((SRC / rel).read_bytes()).hexdigest() == digest, rel


def test_the_recording_verifies_and_states_its_provenance_honestly():
    rec = load(SRC / "recorded" / "fuzz4all", "fuzz4all", 100)
    assert len(rec.inputs) == 100 and rec.available == 100
    p = rec.provenance
    assert "gpt-4.1-mini" in p["model"] and "stated by the author" in p["model"]
    assert "not the Rhino this example runs" in p["sut_at_generation"]
    assert "does not regenerate" in p["note"]


def test_the_disclosure_says_this_is_not_a_controlled_comparison():
    cfg = load_config(SRC / "spreadex.yaml")
    assert "not a controlled comparison" in cfg.raw["presets"]["disclosure"]
    assert "not a controlled comparison" in (SRC / "README.md").read_text()
    assert "fuzzingbook" in cfg.raw["presets"]["not_recommended"]


def test_opening_the_example_never_touches_the_users_project(tmp_path, monkeypatch):
    monkeypatch.setenv("SPREADEX_HOME", str(tmp_path / "home"))
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "spreadex.yaml").write_text("sut: {command: [./mine, '{input}']}\n")
    before = (mine / "spreadex.yaml").read_bytes()
    root = examples.ensure("rhino")
    assert root == tmp_path / "home" / "examples" / "rhino" and (root / "spreadex.yaml").is_file()
    assert (mine / "spreadex.yaml").read_bytes() == before and sorted(p.name for p in mine.iterdir()) == ["spreadex.yaml"]


def test_reopening_keeps_edits_and_history_and_restores_missing_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SPREADEX_HOME", str(tmp_path / "home"))
    root = examples.ensure("rhino")
    (root / "spreadex.yaml").write_text((root / "spreadex.yaml").read_text() + "\n# my edit\n")
    (root / ".spreadex").mkdir()
    (root / ".spreadex" / "corpus.db").write_bytes(b"history")
    (root / "grammars" / "fandango" / "rhino.fan").unlink()
    examples.ensure("rhino")
    assert "# my edit" in (root / "spreadex.yaml").read_text()
    assert (root / ".spreadex" / "corpus.db").read_bytes() == b"history"
    assert (root / "grammars" / "fandango" / "rhino.fan").is_file()
    examples.reset("rhino")
    assert "# my edit" not in (root / "spreadex.yaml").read_text() and not (root / ".spreadex").exists()


def test_minicalc_is_still_the_demo_at_its_old_place(tmp_path, monkeypatch):
    from spreadex import demo

    monkeypatch.setenv("SPREADEX_HOME", str(tmp_path / "home"))
    assert examples.root("minicalc") == demo.demo_root()
    assert examples.source_dir("minicalc") == demo.source_dir()


def _obs(exit_code, stderr="", stdout="", timed_out=False):
    return Observation(input_hash="h", sut_id="sut", sut_version=None, exit_code=exit_code, signal=None,
                       timed_out=timed_out, duration_ms=1.0, stdout_hash="", stderr_hash="",
                       stdout_preview=stdout or None, stderr_preview=stderr or None)


@pytest.mark.parametrize("obs,verdict", [
    (_obs(0, stdout="hi 3"), Verdict.OK),
    (_obs(3, stderr='js: "x.js", line 1: missing variable name\njs: var = ;'), Verdict.EXPECTED_REJECTION),
    (_obs(3, stderr='js: "x.js", line 1: exception from uncaught JavaScript throw: TypeError: x'),
     Verdict.EXPECTED_REJECTION),
    # An engine defect is a Java stack trace -- a crash even when a js: line is printed too.
    (_obs(1, stderr='js: warning\nException in thread "main" java.lang.NullPointerException\n'
                    "\tat org.mozilla.javascript.Interpreter.interpret(Interpreter.java:1)"), Verdict.CRASH),
    (_obs(None, timed_out=True), Verdict.TIMEOUT),
])
def test_rhinos_output_is_classified_by_the_examples_oracle(obs, verdict):
    oracle = make_oracle(load_config(SRC / "spreadex.yaml").oracle)
    assert oracle.judge([obs]).verdict == verdict


# ------------------------------------------------------------------- the real Rhino

@pytest.fixture(scope="module")
def rhino_target():
    from spreadex.exec.runner import Target

    if not shutil.which("java"):
        pytest.skip("needs Java (11+)")
    if runtimes.verified("rhino") is None:
        pytest.skip("needs the pinned Rhino jar: spreadex runtimes install rhino")
    cfg = load_config(SRC / "spreadex.yaml")
    return Target.from_config(cfg.raw["sut"], base_dir=SRC), make_oracle(cfg.oracle)


@pytest.mark.parametrize("program,verdict", [
    ('print("hi " + (1 + 2));', Verdict.OK),
    ("var = ;", Verdict.EXPECTED_REJECTION),                       # syntax error
    ('throw new TypeError("x");', Verdict.EXPECTED_REJECTION),     # uncaught runtime error
    ("undefinedFunction();", Verdict.EXPECTED_REJECTION),          # ReferenceError
    ("while (true) {}", Verdict.TIMEOUT),
])
def test_the_pinned_rhino_runs_and_is_judged(rhino_target, tmp_path, program, verdict):
    from dataclasses import replace

    from spreadex.exec.runner import run_one

    target, oracle = rhino_target
    if verdict is Verdict.TIMEOUT:
        target = replace(target, limits=replace(target.limits, timeout_s=3))
    f = tmp_path / "p.js"
    f.write_text(program)
    assert oracle.judge([run_one(target, f)]).verdict == verdict
