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


def test_grammarinator_is_skipped_with_a_reason(tmp_path):
    result = adapt(RHINO_BNF, ["fuzzingbook", "grammarinator"], tmp_path)
    assert "fuzzingbook" in result.written
    assert "cannot emit" in result.skipped["grammarinator"]


def test_ambiguity_in_the_fandango_grammar_is_reported():
    """rhino.fan defines IDENT_NUM and IDENT_STR identically, which is what
    makes ISLa fail on it at solve time."""
    g = load(FIXTURES / "rhino.fan")
    risks = expressibility(g, "isla").risks
    assert any("IDENT_NUM" in r and "IDENT_STR" in r for r in risks)
