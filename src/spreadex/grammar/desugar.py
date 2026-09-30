"""Rewrite EBNF constructs into plain BNF by introducing helper rules.

ISLa's BNF and FuzzingBook's dict have no repetition or grouping operators, so
a grammar using them cannot be handed to either as-is. Desugaring is what makes
one source grammar usable by every generator.

    <list> ::= "[" <item> (", " <item>)* "]"

becomes

    <list>      ::= "[" <item> <list__s1> "]"
    <list__s1>  ::= "" | <list__g1> <list__s1>
    <list__g1>  ::= ", " <item>
"""

from __future__ import annotations

from .ir import Alt, EPSILON, Grammar, Lit, Node, Ref, Regex, Repeat, Seq

# Unbounded repetition has to stop somewhere when it is expanded into explicit
# alternatives; recursion is preferred, so this only bounds {m,} forms.
UNBOUNDED_EXPANSION = 5


class _Desugarer:
    def __init__(self, grammar: Grammar) -> None:
        self.grammar = grammar
        self.new_rules: dict[str, Node] = {}
        self.counter: dict[str, int] = {}

    def fresh(self, owner: str, kind: str) -> str:
        """A helper rule name that cannot collide with a user's rule."""
        self.counter[owner] = self.counter.get(owner, 0) + 1
        name = f"{owner}__{kind}{self.counter[owner]}"
        while name in self.grammar.rules or name in self.new_rules:
            self.counter[owner] += 1
            name = f"{owner}__{kind}{self.counter[owner]}"
        return name

    def run(self) -> Grammar:
        rules: dict[str, Node] = {}
        for name, body in self.grammar.rules.items():
            rules[name] = self.visit(body, name)
        rules.update(self.new_rules)
        return self.grammar.copy_with(rules)

    def visit(self, node: Node, owner: str) -> Node:
        if isinstance(node, (Lit, Regex, Ref)):
            return node
        if isinstance(node, Alt):
            return Alt(tuple(self.visit(o, owner) for o in node.options))
        if isinstance(node, Seq):
            items = [self.visit(i, owner) for i in node.items]
            # A sequence may not contain an alternation in plain BNF; lift it.
            lifted = [self.lift(i, owner) if isinstance(i, Alt) else i for i in items]
            return lifted[0] if len(lifted) == 1 else Seq(tuple(lifted))
        if isinstance(node, Repeat):
            return self.expand_repeat(node, owner)
        raise TypeError(f"unknown node type: {type(node).__name__}")

    def lift(self, node: Node, owner: str) -> Ref:
        """Move a sub-expression into its own rule and refer to it."""
        name = self.fresh(owner, "g")
        self.new_rules[name] = node
        return Ref(name)

    def expand_repeat(self, node: Repeat, owner: str) -> Node:
        inner = self.visit(node.node, owner)
        # Anything but a single symbol needs its own rule so it can be repeated.
        if not isinstance(inner, (Ref, Lit, Regex)):
            inner = self.lift(inner, owner)

        lo, hi = node.min, node.max

        if hi is None:
            # <r> ::= "" | inner <r>     (right-recursive, so it stays regular)
            tail = self.fresh(owner, "s")
            self.new_rules[tail] = Alt((EPSILON, Seq((inner, Ref(tail)))))
            if lo == 0:
                return Ref(tail)
            required = [inner] * lo
            return Seq(tuple(required + [Ref(tail)]))

        # Bounded: enumerate lo..hi explicitly.
        options: list[Node] = []
        for count in range(lo, hi + 1):
            if count == 0:
                options.append(EPSILON)
            elif count == 1:
                options.append(inner)
            else:
                options.append(Seq(tuple([inner] * count)))
        if len(options) == 1:
            return options[0]
        name = self.fresh(owner, "r")
        self.new_rules[name] = Alt(tuple(options))
        return Ref(name)


def desugar(grammar: Grammar) -> Grammar:
    """Return an equivalent grammar using only alternation and sequencing."""
    if grammar.is_pure_bnf():
        return grammar
    return _Desugarer(grammar).run()


def flatten_alternatives(grammar: Grammar) -> Grammar:
    """Normalize every rule body to a single top-level Alt of Seqs.

    Renderers that emit one line per alternative want this shape; producing it
    once here keeps each renderer from re-deriving it.
    """
    rules: dict[str, Node] = {}
    for name, body in grammar.rules.items():
        options: list[Node] = []
        _collect_alternatives(body, options)
        rules[name] = Alt(tuple(options)) if len(options) > 1 else options[0]
    return grammar.copy_with(rules)


def _collect_alternatives(node: Node, out: list[Node]) -> None:
    if isinstance(node, Alt):
        for option in node.options:
            _collect_alternatives(option, out)
    else:
        out.append(node)
