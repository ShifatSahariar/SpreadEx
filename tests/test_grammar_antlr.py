"""ANTLRv4 as a grammar notation, in both directions.

ANTLR matters twice over: it is what the public grammar zoo is written in, and
it is the only notation Grammarinator consumes.
"""

import pytest

from spreadex.grammar import GrammarError, load, parse_antlr, render
from spreadex.grammar.antlr import DEFAULT_ALPHABET, antlr_rule_name, strip_comments
from spreadex.grammar.ir import Alt, Lit, Ref, Repeat, Seq


def parse(text):
    return parse_antlr(text)[0]


def notes(text):
    return parse_antlr(text)[1]


# ------------------------------------------------------------------ parsing

def test_header_and_simple_rule():
    g = parse("grammar T;\nstart : 'a' b ;\nb : 'c' ;")
    assert g.start == "start"
    assert g.rules["start"] == Seq((Lit("a"), Ref("b")))


def test_alternatives():
    g = parse("grammar T;\nstart : 'a' | 'b' | 'c' ;")
    assert g.rules["start"] == Alt((Lit("a"), Lit("b"), Lit("c")))


@pytest.mark.parametrize("suffix,expected", [
    ("?", (0, 1)), ("*", (0, None)), ("+", (1, None)),
    ("??", (0, 1)), ("*?", (0, None)), ("+?", (1, None)),   # non-greedy
])
def test_repetition_including_non_greedy(suffix, expected):
    """Non-greedy suffixes change parsing, not the language."""
    g = parse(f"grammar T;\nstart : a{suffix} ;\na : 'x' ;")
    node = g.rules["start"]
    assert isinstance(node, Repeat) and (node.min, node.max) == expected


def test_grouping():
    g = parse("grammar T;\nstart : 'a' ('b' | 'c') 'd' ;")
    assert g.rules["start"].items[1] == Alt((Lit("b"), Lit("c")))


def test_character_set_and_range():
    g = parse("grammar T;\nstart : [a-c0] ;")
    assert g.rules["start"] == Alt((Lit("a"), Lit("b"), Lit("c"), Lit("0")))


def test_escapes_in_literals():
    g = parse(r"grammar T;" "\n" r"start : '\n\t\\' ;")
    assert g.rules["start"] == Lit("\n\t\\")


def test_unicode_escape():
    g = parse(r"grammar T;" "\n" r"start : 'A' ;")
    assert g.rules["start"] == Lit("A")


def test_eof_is_empty():
    g = parse("grammar T;\nstart : 'a' EOF ;")
    assert g.rules["start"] == Seq((Lit("a"), Lit("")))


def test_fragment_is_just_another_rule():
    """For generation the lexer/parser split does not exist."""
    g = parse("grammar T;\nstart : DIGIT ;\nfragment DIGIT : '7' ;")
    assert g.rules["DIGIT"] == Lit("7")


def test_labels_are_stripped():
    g = parse("grammar T;\nstart : x=a y+=b ;\na : '1' ;\nb : '2' ;")
    assert g.rules["start"] == Seq((Ref("a"), Ref("b")))


def test_alternative_labels_are_stripped():
    g = parse("grammar T;\nstart : 'a' # First | 'b' # Second ;")
    assert g.rules["start"] == Alt((Lit("a"), Lit("b")))


def test_actions_and_predicates_are_ignored_and_counted():
    n = notes("grammar T;\n@members {x = 1}\nstart : {do()} 'a' {cond}? 'b' ;")
    assert n.ignored_actions >= 2 and n.ignored_predicates == 1


def test_predicates_are_a_warning_because_they_constrain_output():
    n = notes("grammar T;\nstart : {ok}? 'a' ;")
    codes = {f.code for f in n.as_findings()}
    assert "antlr-predicates" in codes


def test_lexer_skip_command_is_recorded():
    n = notes("grammar T;\nstart : WS ;\nWS : ' ' -> skip ;")
    assert "WS" in n.skipped_rules


def test_options_tokens_and_imports_are_skipped():
    g = parse("grammar T;\noptions { tokenVocab=X; }\ntokens { A, B }\n"
              "import Other;\nstart : 'a' ;")
    assert g.rules["start"] == Lit("a")


@pytest.mark.parametrize("construct", ["~[\\r\\n]", "."])
def test_exclusion_sets_expand_against_a_bounded_alphabet(construct):
    """`.` and `~[...]` are defined by exclusion, which is fine when parsing and
    unbounded when generating."""
    g, n = parse_antlr(f"grammar T;\nstart : {construct} ;")
    options = g.rules["start"].options
    assert 80 < len(options) <= len(DEFAULT_ALPHABET)
    assert any("bounded alphabet" in a for a in n.approximated)


def test_negated_set_actually_excludes():
    g = parse("grammar T;\nstart : ~[abc] ;")
    produced = {o.text for o in g.rules["start"].options}
    assert not ({"a", "b", "c"} & produced)


# --------------------------------------------------------------- robustness

def test_apostrophe_in_an_action_comment_does_not_eat_the_grammar():
    """A Python comment reading "the loop's update" breaks any scanner that
    tracks quotes but not the action language's comments."""
    text = (
        "grammar T;\n"
        "@members {\n"
        "# the outer loop's update advances the wrong variable\n"
        "def f(self): pass\n"
        "}\n"
        "start : 'a' ;\n"
    )
    assert parse(text).rules["start"] == Lit("a")


def test_braces_inside_action_strings_do_not_unbalance():
    text = "grammar T;\n@members {\nx = \"}{\"\n}\nstart : 'a' ;\n"
    assert parse(text).rules["start"] == Lit("a")


def test_comment_markers_inside_literals_survive():
    g = parse("grammar T;\nstart : '// not a comment' ;")
    assert g.rules["start"] == Lit("// not a comment")


def test_strip_comments_preserves_line_numbers():
    text = "grammar T;\n/* one\ntwo\nthree */\nstart : 'a' ;"
    assert strip_comments(text).count("\n") == text.count("\n")


@pytest.mark.parametrize("text,message", [
    ("grammar T;\nstart 'a' ;", "expected ':'"),
    ("grammar T;\nstart : ( 'a' ;", "unclosed"),
    ("grammar T;\nstart : 'a", "unterminated literal"),
    ("grammar T;\n", "No rules found"),
])
def test_errors_are_explained(text, message):
    with pytest.raises(GrammarError, match=message):
        parse(text)


# ---------------------------------------------------------------- rendering

def test_render_round_trips():
    source = "grammar T;\nstart : 'a' (b | 'c')* 'd' ;\nb : 'x' | ;"
    g = parse(source)
    back = parse(render(g, "grammarinator", "t.g4"))
    assert set(back.rules) >= {"start", "b"}


def test_rule_names_are_lowercased_for_parser_rules():
    """Everything becomes a parser rule, so ANTLR's rule that a lexer rule may
    not reference a parser rule cannot be violated."""
    g = parse("grammar T;\nstart : IDENT_NUM ;\nIDENT_NUM : '7' ;")
    out = render(g, "grammarinator", "t.g4")
    assert "ident_NUM" in out or "ident_num" in out
    assert "\nIDENT_NUM :" not in out


def test_rule_name_collisions_are_resolved():
    taken = {}
    assert antlr_rule_name("Foo", taken) == "foo"
    assert antlr_rule_name("foo", taken) == "foo2"


def test_reserved_words_are_escaped():
    taken = {}
    assert antlr_rule_name("grammar", taken) == "grammar_"


def test_bounded_repetition_is_written_out():
    """ANTLR has no {m,n}."""
    from spreadex.grammar import parse_bnf

    g = parse_bnf('<start> ::= "x"{2,3}')
    out = render(g, "grammarinator", "t")
    assert "{2,3}" not in out
    assert "'x' 'x'" in out


def test_regex_terminals_are_expanded_not_emitted():
    from spreadex.grammar import parse_bnf

    g = parse_bnf(r"<start> ::= r'[a-c]'")
    out = render(g, "grammarinator", "t")
    assert "r'" not in out
    assert "'a'" in out


def test_emitted_grammar_has_a_valid_header():
    from spreadex.grammar import parse_bnf

    g = parse_bnf('<start> ::= "x"')
    assert "grammar " in render(g, "grammarinator", "my-grammar.bnf")
