"""Parsing into the operator-aware IR."""

import pytest

from spreadex.grammar import Feature, GrammarError, parse_bnf, parse_fuzzingbook
from spreadex.grammar.ir import Alt, Lit, Ref, Regex, Repeat, Seq


def test_simple_rule():
    g = parse_bnf('<start> ::= "a" <b>\n<b> ::= "c"')
    assert g.start == "start"
    assert g.rules["start"] == Seq((Lit("a"), Ref("b")))


def test_alternation_and_continuation():
    g = parse_bnf('<start> ::= "a"\n          | "b"\n          | "c"')
    assert g.rules["start"] == Alt((Lit("a"), Lit("b"), Lit("c")))


def test_indented_continuation_is_not_a_new_rule():
    g = parse_bnf('<start> ::= <a>\n    <b>\n<a> ::= "x"\n<b> ::= "y"')
    assert g.rules["start"] == Seq((Ref("a"), Ref("b")))
    assert set(g.rules) == {"start", "a", "b"}


def test_parentheses_inside_a_terminal_are_not_grouping():
    """`"(" <e> ")"` is three terminals, not a group. A line-based splitter
    gets this wrong, which is why there is a real tokenizer."""
    g = parse_bnf('<start> ::= "(" <e> ")"\n<e> ::= "1"')
    assert g.rules["start"] == Seq((Lit("("), Ref("e"), Lit(")")))
    assert Feature.GROUPING not in g.features()


def test_grouping_is_recognised_when_real():
    g = parse_bnf('<start> ::= "x" (<a> | <b>) "y"\n<a> ::= "1"\n<b> ::= "2"')
    assert Feature.GROUPING in g.features()


@pytest.mark.parametrize("suffix,expected", [
    ("?", (0, 1)), ("*", (0, None)), ("+", (1, None)),
    ("{3}", (3, 3)), ("{1,4}", (1, 4)), ("{2,}", (2, None)),
])
def test_repetition_forms(suffix, expected):
    g = parse_bnf(f'<start> ::= <a>{suffix}\n<a> ::= "x"')
    node = g.rules["start"]
    assert isinstance(node, Repeat)
    assert (node.min, node.max) == expected


def test_regex_terminal():
    g = parse_bnf(r"<start> ::= r'[a-z]{2}'")
    assert g.rules["start"] == Regex("[a-z]{2}")
    assert Feature.REGEX_TERMINAL in g.features()


def test_comments_and_blank_lines_ignored():
    g = parse_bnf('# a comment\n\n<start> ::= "x"  # trailing\n')
    assert g.rules["start"] == Lit("x")


def test_hash_inside_a_string_is_not_a_comment():
    g = parse_bnf('<start> ::= "a#b"')
    assert g.rules["start"] == Lit("a#b")


def test_escapes_in_terminals():
    g = parse_bnf(r'<start> ::= "a\nb"')
    assert g.rules["start"] == Lit("a\nb")


def test_repeated_rule_head_merges_alternatives():
    g = parse_bnf('<start> ::= "a"\n<start> ::= "b"')
    assert g.rules["start"] == Alt((Lit("a"), Lit("b")))


def test_empty_alternative():
    g = parse_bnf('<start> ::= "" | "x"')
    assert Feature.EMPTY_STRING in g.features()


@pytest.mark.parametrize("text,message", [
    ('<start> ::= (', "unclosed"),
    ('<start> ::= "abc', "unterminated"),
    ('start ::= "x"', "expected a rule name"),
    ('<start> "x"', "expected '::='"),
    ('', "No rules found"),
    ('<start> ::= <a>{5,2}', "max below min"),
])
def test_syntax_errors_are_explained(text, message):
    with pytest.raises(GrammarError, match=message):
        parse_bnf(text)


def test_bare_unquoted_terminal_suggests_quoting():
    with pytest.raises(GrammarError, match="must be quoted"):
        parse_bnf("<start> ::= abc")


# ---------------------------------------------------------------- fuzzingbook

def test_fuzzingbook_dict():
    g = parse_fuzzingbook('GRAMMAR = {"<start>": ["<a>b"], "<a>": ["x", "y"]}')
    assert g.rules["start"] == Seq((Ref("a"), Lit("b")))
    assert g.rules["a"] == Alt((Lit("x"), Lit("y")))


def test_fuzzingbook_factory_function():
    text = (
        "def get_thing_grammar():\n"
        "    g = {'<start>': ['<a>'], '<a>': ['x']}\n"
        "    return g\n"
    )
    g = parse_fuzzingbook(text)
    assert set(g.rules) == {"start", "a"}


def test_fuzzingbook_crange_is_expanded():
    g = parse_fuzzingbook("GRAMMAR = {'<start>': ['<d>'], '<d>': crange('0','3')}")
    assert g.rules["d"] == Alt((Lit("0"), Lit("1"), Lit("2"), Lit("3")))


def test_fuzzingbook_module_is_not_executed():
    """A grammar file is data. Importing it would be an arbitrary-code path."""
    text = "import sys\nsys.exit(1)\nGRAMMAR = {'<start>': ['x']}\n"
    g = parse_fuzzingbook(text)          # must not raise SystemExit
    assert g.rules["start"] == Lit("x")


def test_fuzzingbook_without_a_grammar_says_what_it_wanted():
    with pytest.raises(GrammarError, match="No grammar dict found"):
        parse_fuzzingbook("x = 1")
