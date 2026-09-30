"""An operator-aware grammar representation.

The research prototype kept alternatives as verbatim strings and left every
renderer to "translate the operators", which none of them did -- so a `*` in a
grammar emitted for FuzzingBook became a literal asterisk. Converting between
dialects needs structure, so this is a real tree.

    <list> ::= "[" <item> (", " <item>)* "]"

becomes

    Seq(Lit("["), Ref("item"),
        Repeat(Seq(Lit(", "), Ref("item")), 0, None),
        Lit("]"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Union


@dataclass(frozen=True)
class Lit:
    """A terminal string. The empty string is how a grammar spells epsilon."""

    text: str

    def __str__(self) -> str:
        return f'"{self.text}"'


@dataclass(frozen=True)
class Regex:
    """A terminal given as a regular expression, e.g. `r'[a-z]{3}'`."""

    pattern: str

    def __str__(self) -> str:
        return f"r'{self.pattern}'"


@dataclass(frozen=True)
class Ref:
    """A reference to another rule. Stored WITHOUT angle brackets."""

    name: str

    def __str__(self) -> str:
        return f"<{self.name}>"


@dataclass(frozen=True)
class Seq:
    items: tuple["Node", ...]

    def __str__(self) -> str:
        return " ".join(str(i) for i in self.items)


@dataclass(frozen=True)
class Alt:
    options: tuple["Node", ...]

    def __str__(self) -> str:
        return " | ".join(str(o) for o in self.options)


@dataclass(frozen=True)
class Repeat:
    """`?`, `*`, `+` and `{m,n}` are one node: a count range.

    max is None for unbounded. `?` is (0,1), `*` is (0,None), `+` is (1,None).
    """

    node: "Node"
    min: int
    max: int | None

    def __str__(self) -> str:
        inner = f"({self.node})" if isinstance(self.node, (Seq, Alt)) else str(self.node)
        if (self.min, self.max) == (0, 1):
            return f"{inner}?"
        if (self.min, self.max) == (0, None):
            return f"{inner}*"
        if (self.min, self.max) == (1, None):
            return f"{inner}+"
        if self.max is None:
            return f"{inner}{{{self.min},}}"
        if self.min == self.max:
            return f"{inner}{{{self.min}}}"
        return f"{inner}{{{self.min},{self.max}}}"


Node = Union[Lit, Regex, Ref, Seq, Alt, Repeat]

EPSILON = Lit("")


class Feature(str, Enum):
    """A construct a grammar uses, so we can say which dialects can express it."""

    REGEX_TERMINAL = "regex terminal"
    GROUPING = "grouping"
    OPTIONAL = "optional (?)"
    REPEAT_UNBOUNDED = "unbounded repetition (*, +)"
    REPEAT_BOUNDED = "bounded repetition ({m,n})"
    EMPTY_STRING = "empty alternative"


@dataclass
class Grammar:
    start: str
    rules: dict[str, Node] = field(default_factory=dict)
    source_format: str = "bnf"
    source_path: str | None = None

    def __post_init__(self) -> None:
        self.start = self.start.strip("<>")

    # ------------------------------------------------------------- traversal

    def __contains__(self, name: str) -> bool:
        return name.strip("<>") in self.rules

    def walk(self, node: Node) -> Iterator[Node]:
        """Every node in the subtree, including the root."""
        yield node
        if isinstance(node, (Seq,)):
            for item in node.items:
                yield from self.walk(item)
        elif isinstance(node, Alt):
            for option in node.options:
                yield from self.walk(option)
        elif isinstance(node, Repeat):
            yield from self.walk(node.node)

    def walk_all(self) -> Iterator[tuple[str, Node]]:
        for name, body in self.rules.items():
            for node in self.walk(body):
                yield name, node

    def references(self, node: Node) -> set[str]:
        return {n.name for n in self.walk(node) if isinstance(n, Ref)}

    def all_references(self) -> set[str]:
        return {n.name for _, n in self.walk_all() if isinstance(n, Ref)}

    def alternatives(self, name: str) -> list[Node]:
        """Top-level alternatives of a rule, whatever its shape."""
        body = self.rules[name.strip("<>")]
        return list(body.options) if isinstance(body, Alt) else [body]

    # -------------------------------------------------------------- features

    def features(self) -> set[Feature]:
        found: set[Feature] = set()
        for _, node in self.walk_all():
            if isinstance(node, Regex):
                found.add(Feature.REGEX_TERMINAL)
            elif isinstance(node, Lit) and node.text == "":
                found.add(Feature.EMPTY_STRING)
            elif isinstance(node, Repeat):
                if (node.min, node.max) == (0, 1):
                    found.add(Feature.OPTIONAL)
                elif node.max is None:
                    found.add(Feature.REPEAT_UNBOUNDED)
                else:
                    found.add(Feature.REPEAT_BOUNDED)
                if isinstance(node.node, (Seq, Alt)):
                    found.add(Feature.GROUPING)
            elif isinstance(node, Seq):
                # A sequence containing an alternation needs parentheses:
                #   a (b | c) d
                # A plain Alt of Seqs is ordinary BNF and needs nothing.
                if any(isinstance(child, Alt) for child in node.items):
                    found.add(Feature.GROUPING)
            elif isinstance(node, Alt):
                if any(isinstance(child, Alt) for child in node.options):
                    found.add(Feature.GROUPING)
        return found

    STRUCTURAL = (Feature.GROUPING, Feature.OPTIONAL,
                  Feature.REPEAT_UNBOUNDED, Feature.REPEAT_BOUNDED)

    def is_pure_bnf(self) -> bool:
        """True when only alternation and sequencing are used.

        Regex terminals are a terminal *kind*, not structure, so they are not
        counted here -- whether a dialect accepts them is an expressibility
        question answered in diagnose.py.
        """
        return not (self.features() & set(self.STRUCTURAL))

    def reachable(self) -> set[str]:
        seen: set[str] = set()
        stack = [self.start]
        while stack:
            name = stack.pop()
            if name in seen or name not in self.rules:
                continue
            seen.add(name)
            stack.extend(self.references(self.rules[name]))
        return seen

    def copy_with(self, rules: dict[str, Node]) -> "Grammar":
        return Grammar(self.start, rules, self.source_format, self.source_path)
