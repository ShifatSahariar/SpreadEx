"""Desugaring, regex expansion and rendering."""

import pytest

from spreadex.grammar import Feature, RenderError, desugar, parse_bnf, render
from spreadex.grammar.regex_expand import RegexTooComplex, expand_regex


def language(grammar, max_len=6):
    """Every string of length <= max_len that a grammar derives.

    Enumerating by STRING LENGTH rather than by derivation depth is what makes
    this a fair oracle: `<a>+` and its desugared right-recursive form reach the
    same strings, but at very different depths, so a depth-bounded comparison
    would report a false mismatch.
    """
    from spreadex.grammar.ir import Alt, Lit, Ref, Regex, Repeat, Seq

    # Least fixpoint: repeatedly extend each rule's string set until stable.
    sets: dict[str, set[str]] = {name: set() for name in grammar.rules}

    def strings(node) -> set[str]:
        if isinstance(node, Lit):
            return {node.text} if len(node.text) <= max_len else set()
        if isinstance(node, Regex):
            return {f"<regex:{node.pattern}>"}
        if isinstance(node, Ref):
            return sets.get(node.name, set())
        if isinstance(node, Alt):
            out = set()
            for option in node.options:
                out |= strings(option)
            return out
        if isinstance(node, Seq):
            out = {""}
            for item in node.items:
                nxt = set()
                for prefix in out:
                    for suffix in strings(item):
                        combined = prefix + suffix
                        if len(combined) <= max_len:
                            nxt.add(combined)
                out = nxt
                if not out:
                    break
            return out
        if isinstance(node, Repeat):
            out = set()
            count = node.min
            while node.max is None or count <= node.max:
                pieces = {""}
                for _ in range(count):
                    pieces = {p + s for p in pieces for s in strings(node.node)
                              if len(p + s) <= max_len}
                if not pieces and count > node.min:
                    break
                out |= pieces
                count += 1
                if node.max is None and count > max_len + 1:
                    break
            return out
        return set()

    for _ in range(max_len + len(grammar.rules) + 2):
        changed = False
        for name, body in grammar.rules.items():
            found = strings(body)
            if not found <= sets[name]:
                sets[name] |= found
                changed = True
        if not changed:
            break
    return sets[grammar.start]


@pytest.mark.parametrize("source", [
    '<start> ::= "a"? "b"',
    '<start> ::= ("a" | "b") "c"',
    '<start> ::= "x"{2,3}',
    '<start> ::= "a" ("," "a")*',
    '<start> ::= <a>+\n<a> ::= "z"',
])
def test_desugaring_preserves_the_language(source):
    g = parse_bnf(source)
    d = desugar(g)
    assert d.is_pure_bnf(), "desugaring must remove every operator"
    assert language(g) == language(d), "desugaring changed the language"


def test_desugaring_a_pure_grammar_changes_nothing():
    g = parse_bnf('<start> ::= "a" | "b"')
    assert desugar(g) is g


def test_helper_rule_names_do_not_collide():
    g = parse_bnf('<start> ::= <a>*\n<a> ::= "x"\n<start__s1> ::= "taken"')
    d = desugar(g)
    assert d.rules["start__s1"].text == "taken"
    assert len(d.rules) > len(g.rules)


# ------------------------------------------------------------------ regex

@pytest.mark.parametrize("pattern,expected", [
    (r"[abc]", {"a", "b", "c"}),
    (r"\d", set("0123456789")),
    (r"x{2}", {"xx"}),
    (r"a{1,2}", {"a", "aa"}),
])
def test_regex_expansion(pattern, expected):
    g = parse_bnf(f"<start> ::= r'{pattern}'")
    from spreadex.grammar.render import _expand_regexes
    assert language(_expand_regexes(g)) == expected


@pytest.mark.parametrize("pattern", [r"a*", r"a+", r".", r"[^a]"])
def test_regex_that_cannot_be_enumerated_is_refused(pattern):
    with pytest.raises(RegexTooComplex):
        expand_regex(pattern)


# ----------------------------------------------------------------- renderers

@pytest.mark.parametrize("generator", ["fuzzingbook", "isla", "fandango"])
def test_render_round_trips_through_the_parser(generator):
    """What we emit must be what we can read back."""
    from spreadex.grammar import parse_fuzzingbook

    source = '<start> ::= "a" (<b> | "c")* "d"\n<b> ::= "x" | ""'
    g = parse_bnf(source)
    text = render(g, generator, "test")
    reparsed = parse_fuzzingbook(text) if generator == "fuzzingbook" else parse_bnf(text)
    assert language(g) == language(reparsed), f"{generator} round-trip changed the language"


def test_fuzzingbook_output_has_no_operators_left():
    """The bug this module exists to prevent: a `*` arriving as a literal."""
    g = parse_bnf('<start> ::= <a>*\n<a> ::= "x"')
    from spreadex.grammar.ir import Alt, Lit, Seq

    text = render(g, "fuzzingbook", "test")
    from spreadex.grammar import parse_fuzzingbook

    reparsed = parse_fuzzingbook(text)
    for body in reparsed.rules.values():
        for node in reparsed.walk(body):
            if isinstance(node, Lit):
                assert not set("*?+") & set(node.text), f"operator survived as a literal: {node.text!r}"


def test_fandango_keeps_operators_it_understands():
    g = parse_bnf('<start> ::= <a>*\n<a> ::= "x"')
    assert "*" in render(g, "fandango", "test")


def test_fandango_never_emits_pipe_continuation_lines():
    """Fandango rejects both leading- and trailing-pipe continuations; long
    rules must be parenthesised instead."""
    alts = " | ".join(f'"alternative{i}"' for i in range(12))
    g = parse_bnf(f"<start> ::= {alts}")
    for line in render(g, "fandango", "test").splitlines():
        assert not line.strip().startswith("|"), f"leading pipe: {line!r}"
        assert not line.rstrip().endswith("|") or line.strip().startswith(("(", '"')), line


def test_unknown_generator_names_what_can_be_emitted():
    g = parse_bnf('<start> ::= "x"')
    with pytest.raises(RenderError, match="can emit"):
        render(g, "grammarinator", "test")


def test_unenumerable_regex_is_refused_for_a_dialect_without_regex():
    g = parse_bnf(r"<start> ::= r'[a-z]*'")
    with pytest.raises(RenderError):
        render(g, "fuzzingbook", "test")
    assert "r'[a-z]*'" in render(g, "fandango", "test")
