"""Grammar diagnostics, computed on the structure rather than on line text.

The checks a generator will not do for you, and whose absence shows up as a
campaign that produces nothing, hangs, or silently never reaches half the
language. Per-generator expressibility is the part nothing else does: it
answers "can Grammarinator even express this grammar?" before you spend a
budget finding out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .ir import Alt, Feature, Grammar, Lit, Node, Ref, Regex, Repeat, Seq


class Severity(str, Enum):
    ERROR = "error"      # the grammar cannot be used
    WARNING = "warning"  # usable, but it will not do what the author expects
    INFO = "info"


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    rule: str | None = None
    fix: str = ""

    def render(self) -> str:
        mark = {Severity.ERROR: "✗", Severity.WARNING: "!", Severity.INFO: "·"}[self.severity]
        where = f" [{self.rule}]" if self.rule else ""
        out = f"  {mark} {self.code}{where}: {self.message}"
        if self.fix:
            out += f"\n      fix: {self.fix}"
        return out


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity, code, message, rule=None, fix="") -> None:
        self.findings.append(Finding(severity, code, message, rule, fix))


# --------------------------------------------------------------- the analyses

def undefined_references(g: Grammar, report: Report) -> None:
    for name, body in g.rules.items():
        for ref in sorted(g.references(body)):
            if ref not in g.rules:
                report.add(Severity.ERROR, "undefined", f"<{ref}> is used but never defined",
                           rule=name, fix=f"define <{ref}> ::= ...  or correct the spelling")


def start_symbol(g: Grammar, report: Report) -> None:
    if g.start not in g.rules:
        report.add(Severity.ERROR, "no-start", f"start symbol <{g.start}> is not defined",
                   fix="add a <start> rule, or pass --start <name>")


def unreachable_rules(g: Grammar, report: Report) -> None:
    reachable = g.reachable()
    for name in g.rules:
        if name not in reachable:
            report.add(Severity.WARNING, "unreachable",
                       f"<{name}> cannot be reached from <{g.start}>", rule=name,
                       fix="reference it from a reachable rule, or delete it")


def productive_rules(g: Grammar) -> set[str]:
    """Rules that can derive a finite string, by least-fixpoint.

    The prototype approximated this by asking whether an alternative contained
    any non-nonterminal text, which passes `<a> ::= <a> "x"` -- a rule that can
    never terminate.
    """
    productive: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, body in g.rules.items():
            if name in productive:
                continue
            if _can_produce(body, productive, g):
                productive.add(name)
                changed = True
    return productive


def _can_produce(node: Node, productive: set[str], g: Grammar) -> bool:
    if isinstance(node, (Lit, Regex)):
        return True
    if isinstance(node, Ref):
        return node.name in productive
    if isinstance(node, Seq):
        return all(_can_produce(i, productive, g) for i in node.items)
    if isinstance(node, Alt):
        return any(_can_produce(o, productive, g) for o in node.options)
    if isinstance(node, Repeat):
        # Zero repetitions is itself a production.
        return node.min == 0 or _can_produce(node.node, productive, g)
    return False


def non_productive_rules(g: Grammar, report: Report) -> None:
    productive = productive_rules(g)
    reachable = g.reachable()
    for name in g.rules:
        if name not in productive:
            severity = Severity.ERROR if name in reachable else Severity.WARNING
            report.add(severity, "non-productive",
                       f"<{name}> can never derive a finite string "
                       f"(every alternative recurses without a base case)",
                       rule=name,
                       fix="add an alternative that terminates, e.g. a literal or \"\"")


def _first_symbols(node: Node) -> set[str]:
    """Nonterminals this node can begin with, treating nullable prefixes."""
    if isinstance(node, Ref):
        return {node.name}
    if isinstance(node, (Lit, Regex)):
        return set()
    if isinstance(node, Alt):
        out: set[str] = set()
        for option in node.options:
            out |= _first_symbols(option)
        return out
    if isinstance(node, Repeat):
        return _first_symbols(node.node)
    if isinstance(node, Seq):
        out = set()
        for item in node.items:
            out |= _first_symbols(item)
            if not _is_nullable_shallow(item):
                break
        return out
    return set()


def _is_nullable_shallow(node: Node) -> bool:
    if isinstance(node, Lit):
        return node.text == ""
    if isinstance(node, Repeat):
        return node.min == 0
    if isinstance(node, Alt):
        return any(_is_nullable_shallow(o) for o in node.options)
    return False


def left_recursion(g: Grammar, report: Report) -> None:
    """Find cycles in the "can start with" relation.

    Direct or indirect left recursion makes a top-down generator recurse
    forever. Generators differ in how they cope -- FuzzingBook may hit Python's
    recursion limit, ISLa may not terminate -- so this is a warning naming the
    cycle rather than a hard error.
    """
    first = {name: _first_symbols(body) for name, body in g.rules.items()}
    colour: dict[str, int] = {}
    reported: set[frozenset[str]] = set()

    def visit(name: str, path: list[str]) -> None:
        colour[name] = 1
        for nxt in sorted(first.get(name, ())):
            if nxt not in g.rules:
                continue
            if colour.get(nxt, 0) == 1:
                cycle = path[path.index(nxt):] + [nxt] if nxt in path else [name, nxt]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    chain = " -> ".join(f"<{c}>" for c in cycle)
                    report.add(Severity.WARNING, "left-recursion",
                               f"left recursion: {chain}", rule=cycle[0],
                               fix="rewrite so the recursive alternative consumes a "
                                   "terminal first, e.g. <e> ::= <t> | <t> \"+\" <e>")
            elif colour.get(nxt, 0) == 0:
                visit(nxt, path + [nxt])
        colour[name] = 2

    for name in g.rules:
        if colour.get(name, 0) == 0:
            visit(name, [name])


def empty_alternatives(g: Grammar, report: Report) -> None:
    for name in g.rules:
        alts = g.alternatives(name)
        if len(alts) > 1 and sum(1 for a in alts if isinstance(a, Lit) and a.text == "") > 1:
            report.add(Severity.WARNING, "duplicate-empty",
                       f"<{name}> lists the empty alternative more than once", rule=name,
                       fix="remove the duplicate; it only skews the probabilities")


def duplicate_rules(g: Grammar) -> list[tuple[str, str]]:
    """Pairs of rules with structurally identical bodies.

    Two rules deriving the same language make the grammar ambiguous: a string
    has more than one parse tree. Generators that only *produce* strings
    (FuzzingBook, Fandango) are unaffected; ISLa parses, and rejects the
    ambiguity at runtime with a message about unexpected child symbols.

    Full ambiguity is undecidable; this catches the decidable, and by far the
    most common, case.
    """
    by_body: dict[str, list[str]] = {}
    for name, body in g.rules.items():
        by_body.setdefault(str(body), []).append(name)
    pairs: list[tuple[str, str]] = []
    for names in by_body.values():
        if len(names) > 1:
            first = names[0]
            for other in names[1:]:
                pairs.append((first, other))
    return pairs


def ambiguous_rules(g: Grammar, report: Report) -> None:
    for a, b in duplicate_rules(g):
        report.add(Severity.WARNING, "ambiguous",
                   f"<{a}> and <{b}> derive the same language, so the grammar is ambiguous",
                   rule=a,
                   fix="give them disjoint definitions, or merge them into one rule. "
                       "ISLa parses what it generates and may reject this; FuzzingBook "
                       "and Fandango only produce strings and are unaffected.")
    for name in g.rules:
        alts = g.alternatives(name)
        seen: set[str] = set()
        for alt in alts:
            key = str(alt)
            if key in seen:
                report.add(Severity.WARNING, "duplicate-alternative",
                           f"<{name}> lists the alternative {key} more than once", rule=name,
                           fix="remove the duplicate; it only skews the probabilities")
                break
            seen.add(key)


# ------------------------------------------------------------ expressibility

#: What each generator's grammar dialect can express directly.
DIALECT_SUPPORT: dict[str, set[Feature]] = {
    # Fandango: BNF plus EBNF operators and regex terminals.
    "fandango": {Feature.GROUPING, Feature.OPTIONAL, Feature.REPEAT_UNBOUNDED,
                 Feature.REPEAT_BOUNDED, Feature.REGEX_TERMINAL, Feature.EMPTY_STRING},
    # FuzzingBook: a dict of alternatives. No operators, no regex.
    "fuzzingbook": {Feature.EMPTY_STRING},
    # ISLa: plain BNF.
    "isla": {Feature.EMPTY_STRING},
    # Grammarinator consumes ANTLRv4, which has all of these -- but SpreadEx
    # cannot emit .g4 yet, so it is reported as unsupported by the adapter.
    "grammarinator": {Feature.GROUPING, Feature.OPTIONAL, Feature.REPEAT_UNBOUNDED,
                      Feature.REPEAT_BOUNDED, Feature.REGEX_TERMINAL, Feature.EMPTY_STRING},
}


@dataclass
class Expressibility:
    generator: str
    directly: bool                   # expressible without rewriting
    after_rewrite: bool              # expressible once desugared/expanded
    missing: set[Feature] = field(default_factory=set)
    blockers: list[str] = field(default_factory=list)
    #: Reasons this may fail at run time that we cannot decide up front.
    risks: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        # A blocker is fatal whether or not rewriting is needed.
        return not self.blockers and (self.directly or self.after_rewrite)


def expressibility(g: Grammar, generator: str) -> Expressibility:
    """Can this generator express this grammar, directly or after rewriting?

    Everything structural (grouping, `?`, `*`, `{m,n}`) survives desugaring into
    plain BNF. Regex terminals survive only when they can be enumerated.
    """
    from .regex_expand import RegexTooComplex, expand_regex

    supported = DIALECT_SUPPORT.get(generator, set())
    used = g.features()
    missing = used - supported

    blockers: list[str] = []
    risks: list[str] = []

    # ISLa parses the strings it generates, so an ambiguous grammar can make it
    # fail at solve time with a message about unexpected child symbols.
    # Deliberately a RISK and not a blocker: rhino.bnf contains a duplicate rule
    # pair and ISLa handles it, while rhino.fan contains one and ISLa does not.
    # We cannot predict which, so we warn rather than refuse.
    if generator == "isla":
        for a, b in duplicate_rules(g):
            risks.append(
                f"<{a}> and <{b}> derive the same language; ISLa may reject this at solve time"
            )

    if Feature.REGEX_TERMINAL in missing:
        for name, node in g.walk_all():
            if isinstance(node, Regex):
                try:
                    expand_regex(node.pattern)
                except RegexTooComplex as exc:
                    blockers.append(f"<{name}>: r'{node.pattern}' cannot be enumerated ({exc})")

    return Expressibility(
        generator=generator,
        directly=not missing,
        after_rewrite=not blockers,
        missing=missing,
        blockers=blockers,
        risks=risks,
    )


# ---------------------------------------------------------------- entry point

def diagnose(g: Grammar) -> Report:
    report = Report()
    start_symbol(g, report)
    undefined_references(g, report)
    if report.errors:
        # Later analyses would report cascading nonsense on a broken graph.
        return report
    non_productive_rules(g, report)
    unreachable_rules(g, report)
    left_recursion(g, report)
    empty_alternatives(g, report)
    ambiguous_rules(g, report)
    return report
