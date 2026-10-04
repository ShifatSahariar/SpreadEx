"""The bundled demo: a real campaign against a system under test we own.

These tests protect the thing a first-time user sees, which means they test
the SUT's *behaviour* -- a demo whose defect quietly stops being reachable
would still pass a test that only checked files were copied.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from spreadex.demo import DEMO_FILES, materialize, source_dir

CALC = source_dir() / "calc.py"


def run_calc(tmp_path: Path, text: str) -> subprocess.CompletedProcess:
    f = tmp_path / "in.txt"
    f.write_text(text)
    return subprocess.run([sys.executable, str(CALC), str(f)],
                          capture_output=True, text=True, timeout=30)


# ------------------------------------------------------- the demo SUT itself

def test_valid_expressions_evaluate(tmp_path):
    r = run_calc(tmp_path, "1 + 2 * (3 - 1)")
    assert r.returncode == 0
    assert float(r.stdout.strip()) == 5.0


@pytest.mark.parametrize("text", ["1 +", "((1)", "1 @ 2", "", "1 / 0"])
def test_input_it_cannot_read_is_reported_not_crashed(tmp_path, text):
    """The behaviour the whole Observation-vs-Verdict story rests on. If these
    ever started looking like crashes, the demo would teach the opposite of
    what it is for."""
    r = run_calc(tmp_path, text)
    assert r.returncode == 1
    assert r.stderr.startswith("calc: SyntaxError:")
    assert "Traceback" not in r.stderr


def test_the_documented_defect_is_still_reachable(tmp_path):
    """`%` is missing from the division-by-zero guard. A demo whose defect
    stopped being reachable would quietly become a demo that proves nothing."""
    r = run_calc(tmp_path, "1 % 0")
    assert r.returncode != 0
    assert "ZeroDivisionError" in r.stderr
    assert "calc: SyntaxError" not in r.stderr, "this one is a crash, not a rejection"


def test_the_defect_is_reachable_through_the_grammar_too(tmp_path):
    """Shaped like what a generator actually produces, not a hand-minimised
    case: the operator space the grammar explores leads into it."""
    r = run_calc(tmp_path, "7 % 1 * 0 + (0 % 9 - 3 - 4) / 9 * 2 % 0")
    assert "ZeroDivisionError" in r.stderr


# ----------------------------------------------------------- materialisation

def test_the_demo_materialises_a_complete_project(tmp_path):
    project = materialize(tmp_path / "demo")
    for name in DEMO_FILES:
        assert (project / name).is_file(), name
    assert (project / "spreadex.yaml").read_text().count("rejection_patterns") == 1
    assert list((project / "seeds").glob("*.txt")), "a seed corpus ships with it"


def test_the_demo_config_loads(tmp_path):
    """It is the first spreadex.yaml anyone reads, so it has to be valid and
    say what it means."""
    from spreadex.core.config import load_config

    project = materialize(tmp_path / "demo")
    config = load_config(project / "spreadex.yaml")
    assert config.generators == ["fuzzingbook"]
    assert config.raw["oracle"]["rejection_patterns"] == ["^calc: SyntaxError"]
    assert config.raw["grammar"]["source"].endswith("calc.bnf")


def test_the_demo_grammar_is_valid_and_drives_every_dialect(tmp_path):
    """One grammar, four dialects -- the claim the demo makes out loud."""
    from spreadex.grammar import RENDERERS, diagnose, load

    grammar = load(source_dir() / "calc.bnf")
    report = diagnose(grammar)
    assert not report.errors, report.errors
    for name, render in RENDERERS.items():
        assert render(grammar).strip(), name


def test_it_refuses_to_clobber_an_existing_demo(tmp_path):
    project = materialize(tmp_path / "demo")
    (project / "calc.py").write_text("# someone edited this\n")
    with pytest.raises(FileExistsError):
        materialize(project)
    assert (project / "calc.py").read_text() == "# someone edited this\n"
    materialize(project, force=True)
    assert "SyntaxErr" in (project / "calc.py").read_text()


def test_the_rejection_pattern_matches_what_calc_actually_prints(tmp_path):
    """The config and the SUT have to agree, or the demo reports 100 crashes
    that are not crashes. Checked against real output, not a copy of it."""
    import re

    from spreadex.core.config import load_config

    project = materialize(tmp_path / "demo")
    pattern = load_config(project / "spreadex.yaml").raw["oracle"]["rejection_patterns"][0]
    r = run_calc(tmp_path, "1 +")
    assert re.search(pattern, r.stderr, re.MULTILINE)
