"""The adapter against the real grammars from the ICST 2026 package.

Synthetic grammars exercise the code paths; these exercise the actual notation
people write, including the constructs that broke the first implementation.
"""

from pathlib import Path

import pytest

from spreadex.grammar import adapt, diagnose, expressibility, load, render

FIXTURES = Path(__file__).parent / "fixtures" / "grammars"
RHINO_BNF = Path(__file__).resolve().parents[1] / "examples" / "rhino" / "grammars" / "rhino.bnf"


@pytest.mark.parametrize("name,expect_pure", [
    ("rhino.fan", False),                # EBNF: {m,n}, (...)*, ?, regex
    ("rhino.fuzzingbook.py", True),      # a plain dict
])
def test_real_grammars_parse(name, expect_pure):
    g = load(FIXTURES / name)
    assert len(g.rules) > 20
    assert g.start in g.rules
    assert g.is_pure_bnf() is expect_pure


def test_the_bnf_source_parses_and_is_clean():
    g = load(RHINO_BNF)
    assert diagnose(g).ok, "the example's grammar must have no errors"


@pytest.mark.parametrize("generator", ["fuzzingbook", "isla", "fandango"])
def test_every_dialect_can_be_derived_from_the_bnf_source(generator, tmp_path):
    result = adapt(RHINO_BNF, [generator], tmp_path)
    assert result.ok
    path = result.written[generator]
    assert path.exists() and path.stat().st_size > 0


def test_ebnf_source_derives_dialects_that_have_no_operators(tmp_path):
    """rhino.fan uses every EBNF construct; the derived BNF must use none."""
    result = adapt(FIXTURES / "rhino.fan", ["isla", "fuzzingbook"], tmp_path)
    assert result.ok
    for generator in ("isla", "fuzzingbook"):
        derived = load(result.written[generator])
        assert derived.is_pure_bnf(), f"{generator} grammar still has operators"


def test_character_classes_become_shared_rules_not_inlined(tmp_path):
    """Inlining `[A-Za-z]` at every use made the derived grammar 870 lines and
    produced a shape ISLa rejected."""
    result = adapt(FIXTURES / "rhino.fan", ["isla"], tmp_path)
    text = result.written["isla"].read_text()
    assert len(text.splitlines()) < 500, "derived grammar is ballooning again"
    derived = load(result.written["isla"])
    class_rules = [n for n in derived.rules if "__c" in n]
    assert class_rules, "character classes should be lifted into their own rules"


def test_every_generator_can_be_reached_from_one_bnf_source(tmp_path):
    """The point of the adapter: four generators, four notations, one source."""
    result = adapt(RHINO_BNF, ["fuzzingbook", "isla", "fandango", "grammarinator"], tmp_path)
    assert result.ok
    assert set(result.written) == {"fuzzingbook", "isla", "fandango", "grammarinator"}
    assert not result.skipped
    assert result.written["grammarinator"].suffix == ".g4"


def test_ambiguity_in_the_fandango_grammar_is_reported():
    """rhino.fan defines IDENT_NUM and IDENT_STR identically, which is what
    makes ISLa fail on it at solve time."""
    g = load(FIXTURES / "rhino.fan")
    risks = expressibility(g, "isla").risks
    assert any("IDENT_NUM" in r and "IDENT_STR" in r for r in risks)


# ------------------------------------------------------- real ANTLR grammars

ANTLR_FIXTURES = ["rhino.g4", "basic.g4", "lua_constraints.g4"]
CLUSGRAM = Path("/Users/usi/Documents/RESEARCH/ClusGram/subjects")


@pytest.mark.parametrize("name", ANTLR_FIXTURES)
def test_real_antlr_grammars_parse_cleanly(name):
    from spreadex.grammar import diagnose, load

    g = load(FIXTURES / name)
    assert len(g.rules) > 50
    assert diagnose(g).ok, f"{name} produced grammar errors"


def test_lexer_rules_and_negation_are_handled():
    """basic.g4 has real lexer rules with character sets and `~[\\r\\n]`."""
    from spreadex.grammar import parse_antlr

    g, notes = parse_antlr((FIXTURES / "basic.g4").read_text())
    assert any("bounded alphabet" in a for a in notes.approximated)
    assert "REM_LINE" in g.rules


def test_a_constraints_grammar_reports_what_it_dropped():
    """The constraint grammars carry semantic predicates, which cannot run
    during generation -- the user has to be told."""
    from spreadex.grammar import parse_antlr

    _, notes = parse_antlr((FIXTURES / "lua_constraints.g4").read_text())
    assert notes.ignored_predicates > 0
    assert any(f.code == "antlr-predicates" for f in notes.as_findings())


@pytest.mark.parametrize("name", ANTLR_FIXTURES)
def test_antlr_round_trip_preserves_every_rule(name):
    from spreadex.grammar import load, parse_antlr, render

    g = load(FIXTURES / name)
    back = parse_antlr(render(g, "grammarinator", name))[0]
    assert len(back.rules) == len(g.rules), "a rule was lost in the round trip"


@pytest.mark.skipif(not CLUSGRAM.is_dir(), reason="ClusGram subjects not present")
def test_every_clusgram_grammar_parses():
    """The whole corpus: 6 subjects x plain and constraint variants."""
    from spreadex.grammar import diagnose, load

    paths = sorted(CLUSGRAM.glob("*/grammars/grammarinator/*.g4"))
    assert len(paths) >= 12, f"expected the full corpus, found {len(paths)}"
    failures = []
    for path in paths:
        try:
            g = load(path)
            if not diagnose(g).ok:
                failures.append((path.name, "grammar errors"))
        except Exception as exc:  # noqa: BLE001 - reporting every failure at once
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"{len(failures)} grammar(s) failed: {failures}"
