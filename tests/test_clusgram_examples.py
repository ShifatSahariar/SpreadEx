"""The ClusGram subject examples.

Each needs a system under test we are not allowed to ship, so the campaigns
themselves only run when the environment points at one. What is always
checked is the part that silently rots: that the configs load, that the
oracle patterns match the diagnostics the real engines actually print, and
that the grammars still drive every generator.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from spreadex.core.config import load_config

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CLUSGRAM = ["rhino", "nashorn", "graaljs", "karatejs", "basic", "rhino-vs-graaljs"]


@pytest.mark.parametrize("name", CLUSGRAM)
def test_the_example_loads(name, monkeypatch):
    """Every env var the config references gets a value so the parse is real;
    nothing is executed."""
    for var in ("RHINO_JAR", "NASHORN_SUT", "GRAALJS_JARS", "KARATE_RUNNER",
                "KARATE_JARS", "BASIC_CLASSES"):
        monkeypatch.setenv(var, "/nonexistent")
    config = load_config(EXAMPLES / name / "spreadex.yaml")
    assert config.targets
    assert config.generators, f"{name} configures no generator"
    assert config.raw["oracle"]["rejection_patterns"], (
        f"{name} has no rejection patterns; every refused input would be "
        f"reported as a crash"
    )


@pytest.mark.parametrize("name", CLUSGRAM)
def test_crash_patterns_are_checked_before_rejection_patterns(name, monkeypatch):
    """The ordering that stops a broad rejection rule hiding a real bug. BASIC
    is the proof it matters: it catches its own overflow, prints 'Caught an
    Exception' and exits 0."""
    from spreadex.exec.oracle import make_oracle

    for var in ("RHINO_JAR", "NASHORN_SUT", "GRAALJS_JARS", "KARATE_RUNNER",
                "KARATE_JARS", "BASIC_CLASSES"):
        monkeypatch.setenv(var, "/nonexistent")
    raw = load_config(EXAMPLES / name / "spreadex.yaml").raw["oracle"]
    assert raw.get("crash_patterns"), f"{name} declares no crash patterns"
    make_oracle(raw)  # must build


def test_the_javascript_grammar_is_shared_not_copied():
    """One grammar, three engines. Three copies of JavaScript would be exactly
    the work this tool exists to remove."""
    shared = EXAMPLES / "grammars" / "javascript.bnf"
    assert shared.is_file()
    for name in ("rhino", "nashorn", "graaljs", "rhino-vs-graaljs"):
        text = (EXAMPLES / name / "spreadex.yaml").read_text()
        assert "../grammars/javascript.bnf" in text, name


def test_karatejs_has_its_own_grammar_and_says_why():
    """It differs by one rule -- console.log rather than print -- and that is
    a different language, not a variant."""
    own = EXAMPLES / "karatejs" / "karatejs.bnf"
    shared = EXAMPLES / "grammars" / "javascript.bnf"
    assert "console.log" in own.read_text()
    assert "console.log" not in shared.read_text()
    assert "print(" in shared.read_text()
    assert "console.log" in own.read_text()
    # The header has to explain it, or the next person "tidies up" the copy.
    assert "console.log" in own.read_text()[:1200]


def test_basic_is_the_one_that_needs_stdin():
    """Under file mode JavaBASIC would sit at its prompt and every input would
    be recorded as a timeout."""
    config_text = (EXAMPLES / "basic" / "spreadex.yaml").read_text()
    assert "input_mode: stdin" in config_text
    for name in ("rhino", "nashorn", "graaljs", "karatejs"):
        assert "input_mode: stdin" not in (EXAMPLES / name / "spreadex.yaml").read_text()


def test_the_graaljs_banner_is_silenced_at_the_source():
    """Seventeen lines of warning on every run would make every input look
    like a divergence in the differential campaign."""
    for name in ("graaljs", "rhino-vs-graaljs"):
        text = (EXAMPLES / name / "spreadex.yaml").read_text()
        assert "AttachLibraryFailureAction=ignore" in text, name
        assert "WarnInterpreterOnly=false" in text, name


def test_no_example_hardcodes_a_path_on_this_machine():
    """These configs ship. A path into someone's home directory means the
    example works on exactly one computer."""
    offenders = []
    for path in EXAMPLES.rglob("spreadex.yaml"):
        text = path.read_text()
        for needle in ("/Users/", "/home/", "RESEARCH/"):
            if needle in text:
                offenders.append(f"{path.relative_to(EXAMPLES)}: {needle}")
    assert not offenders, offenders


# ----------------------------------------- the patterns against real output

REAL_DIAGNOSTICS = {
    # Exactly what each engine printed when handed `var x = ;`, captured by
    # running them. A pattern list that drifts from reality is how a campaign
    # starts reporting hundreds of working refusals as crashes.
    "nashorn": "Runtime Error: <eval>:1:8 Expected an operand but found ;",
    "graaljs": "SyntaxError: bad.js:1:8 Expected an operand but found ;",
    "karatejs": "JS ERROR: ParserException: expected: [EXPR]",
    "basic": "Syntax Error : Syntax Error : missing = in assignment statement.",
}


@pytest.mark.parametrize("name,diagnostic", sorted(REAL_DIAGNOSTICS.items()))
def test_rejection_patterns_match_what_the_engine_really_prints(name, diagnostic, monkeypatch):
    for var in ("RHINO_JAR", "NASHORN_SUT", "GRAALJS_JARS", "KARATE_RUNNER",
                "KARATE_JARS", "BASIC_CLASSES"):
        monkeypatch.setenv(var, "/nonexistent")
    patterns = load_config(EXAMPLES / name / "spreadex.yaml").raw["oracle"]["rejection_patterns"]
    assert any(re.search(p, diagnostic, re.MULTILINE) for p in patterns), (
        f"{name}: nothing in {patterns} matches what it actually prints:\n  {diagnostic}"
    )


def test_basic_treats_a_runtime_error_as_a_refusal_not_a_crash(monkeypatch):
    """The regression that cost 125 false crashes: JavaBASIC diagnoses a jump
    to an undefined line perfectly well, and an earlier pattern list missed
    the wording."""
    monkeypatch.setenv("BASIC_CLASSES", "/nonexistent")
    patterns = load_config(EXAMPLES / "basic" / "spreadex.yaml").raw["oracle"]["rejection_patterns"]
    real = "Runtime Error: Runtime Error: GOTO non-existent line 80."
    assert any(re.search(p, real, re.MULTILINE) for p in patterns)


def test_basic_still_calls_the_real_overflow_a_crash(monkeypatch):
    """And the fix must not have gone too far: the genuine bug exits 0 and is
    caught by BASIC itself, so only crash_patterns can see it."""
    from spreadex.exec.oracle import looks_like_crash, looks_like_rejection

    monkeypatch.setenv("BASIC_CLASSES", "/nonexistent")
    oracle = load_config(EXAMPLES / "basic" / "spreadex.yaml").raw["oracle"]
    real = ("Caught an Exception :\n"
            "java.lang.ArrayIndexOutOfBoundsException: Index 256 out of bounds for length 256\n"
            "\tat basic.LexicalTokenizer.reset(LexicalTokenizer.java:84)")
    assert looks_like_crash(real, "", oracle["crash_patterns"])
    assert not looks_like_rejection(real, "", oracle["rejection_patterns"]), (
        "the overflow must not be swallowed as a refusal"
    )


def test_the_karate_harness_exists_and_fixes_the_exit_code():
    """Karate's own launcher exits 0 on error, so a campaign would report
    every input as a pass."""
    src = (EXAMPLES / "karatejs" / "KarateRunner.java").read_text()
    assert "System.exit(2)" in src, "a refusal must be non-zero"
    assert "StackOverflowError" in src and "throw fatal" in src, (
        "engine-level failures must escape rather than be reported as refusals"
    )


def test_each_example_explains_how_to_get_the_system_under_test():
    """We ship a configuration, never the SUT. Every example has to say what
    to build and which environment variable points at it."""
    for name in CLUSGRAM:
        readme = EXAMPLES / name / "README.md"
        assert readme.is_file(), f"{name} has no README"
        text = readme.read_text()
        config = (EXAMPLES / name / "spreadex.yaml").read_text()
        for var in re.findall(r"\$\{(\w+)\}", config):
            assert var in text, f"{name}: README never mentions ${var}"


def test_the_shared_grammar_caveat_is_documented():
    """A user who copies one example directory gets a broken config, because
    the grammar is one level up."""
    for name in ("rhino", "nashorn", "graaljs", "rhino-vs-graaljs"):
        text = (EXAMPLES / name / "README.md").read_text()
        assert "Copying this example" in text, name


def test_basic_names_its_licence_restriction_where_it_will_be_read():
    """Non-commercial only, no LICENSE file. That belongs in the README and
    the config, not only in a docs page nobody opens."""
    for path in (EXAMPLES / "basic" / "README.md", EXAMPLES / "basic" / "spreadex.yaml"):
        text = path.read_text().upper()
        assert "NON-COMMERCIAL" in text, path.name
