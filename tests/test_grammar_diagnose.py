"""Grammar diagnostics and per-generator expressibility."""

import pytest

from spreadex.grammar import Feature, Severity, diagnose, expressibility, parse_bnf


def codes(grammar_text):
    return {f.code for f in diagnose(parse_bnf(grammar_text)).findings}


def test_clean_grammar_has_no_findings():
    assert codes('<start> ::= "a" <b>\n<b> ::= "c"') == set()


def test_undefined_reference():
    report = diagnose(parse_bnf('<start> ::= <missing>'))
    assert [f.code for f in report.errors] == ["undefined"]
    assert not report.ok


def test_non_productive_rule_is_an_error():
    """`<a> ::= <a> "x"` can never terminate. The prototype's check passed it,
    because the alternative contained some non-nonterminal text."""
    report = diagnose(parse_bnf('<start> ::= <a>\n<a> ::= <a> "x"'))
    assert any(f.code == "non-productive" for f in report.errors)


def test_productive_through_an_alternative_is_fine():
    assert "non-productive" not in codes('<start> ::= <a>\n<a> ::= <a> "x" | "base"')


def test_productive_through_zero_repetition():
    assert "non-productive" not in codes('<start> ::= <a>*\n<a> ::= <a> "x" | "y"')


def test_unreachable_rule_is_a_warning():
    report = diagnose(parse_bnf('<start> ::= "a"\n<orphan> ::= "b"'))
    assert report.ok
    assert [f.code for f in report.warnings] == ["unreachable"]


def test_direct_left_recursion():
    assert "left-recursion" in codes('<start> ::= <e>\n<e> ::= <e> "+" <t> | <t>\n<t> ::= "1"')


def test_indirect_left_recursion():
    assert "left-recursion" in codes(
        '<start> ::= <a>\n<a> ::= <b> "x" | "z"\n<b> ::= <a> "y" | "w"'
    )


def test_right_recursion_is_not_flagged():
    """Right recursion is how BNF expresses repetition; flagging it would make
    the check useless noise."""
    assert "left-recursion" not in codes('<start> ::= <l>\n<l> ::= "" | "x" <l>')


def test_recursion_after_a_terminal_is_not_left_recursion():
    assert "left-recursion" not in codes('<start> ::= <e>\n<e> ::= "(" <e> ")" | "x"')


def test_ambiguity_between_identical_rules():
    report = diagnose(parse_bnf('<start> ::= <a> | <b>\n<a> ::= "x"\n<b> ::= "x"'))
    assert any(f.code == "ambiguous" for f in report.warnings)


def test_duplicate_alternative_within_a_rule():
    assert "duplicate-alternative" in codes('<start> ::= "x" | "x"')


def test_broken_graph_short_circuits():
    """With an undefined reference, later analyses would report cascading
    nonsense, so they are skipped."""
    report = diagnose(parse_bnf('<start> ::= <missing> <also_missing>'))
    assert all(f.code == "undefined" for f in report.findings)


# ------------------------------------------------------------ expressibility

EBNF = '<start> ::= <a>* "x"\n<a> ::= "y"'


@pytest.mark.parametrize("generator,directly", [
    ("fandango", True),      # has the operators
    ("fuzzingbook", False),  # needs desugaring
    ("isla", False),
])
def test_operator_support_per_generator(generator, directly):
    exp = expressibility(parse_bnf(EBNF), generator)
    assert exp.directly is directly
    assert exp.usable, "everything structural survives desugaring"


def test_enumerable_regex_is_usable_everywhere():
    g = parse_bnf(r"<start> ::= r'[a-c]{2}'")
    for generator in ("fandango", "fuzzingbook", "isla"):
        assert expressibility(g, generator).usable


def test_unenumerable_regex_blocks_dialects_without_regex():
    g = parse_bnf(r"<start> ::= r'[a-z]*'")
    assert expressibility(g, "fandango").usable
    for generator in ("fuzzingbook", "isla"):
        exp = expressibility(g, generator)
        assert not exp.usable
        assert exp.blockers


def test_ambiguity_is_a_risk_for_isla_not_a_blocker():
    """We have grammars both ways: rhino.bnf is ambiguous and ISLa handles it,
    rhino.fan is ambiguous and ISLa does not. So this cannot be a hard rule."""
    g = parse_bnf('<start> ::= <a> | <b>\n<a> ::= "x"\n<b> ::= "x"')
    exp = expressibility(g, "isla")
    assert exp.usable
    assert exp.risks
    assert not expressibility(g, "fandango").risks
