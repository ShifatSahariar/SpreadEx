"""Grammar and constraint assistance, with a deterministic gate on every answer.

The rule from the design audit: a model PROPOSES, SpreadEx VERIFIES. Nothing a
model writes reaches a campaign without passing the same parser and diagnostics
that a hand-written grammar passes, and when it fails the error is fed back and
the model tries again -- a bounded loop, not an open-ended chat.

That is what makes this safe to offer: the worst case is "no usable grammar
was produced", never "a plausible-looking grammar silently tested the wrong
language".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..grammar import GrammarError, diagnose, expressibility, parse_bnf
from .client import LLMError, complete, extract_code_block

MAX_ATTEMPTS = 3
MAX_EXAMPLES = 40
MAX_EXAMPLE_CHARS = 2500


@dataclass
class Attempt:
    n: int
    grammar: str
    ok: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    """What a model suggested, and what the validator made of it."""

    kind: str
    text: str = ""
    ok: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    rules: int = 0
    start: str = ""
    support: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "text": self.text, "ok": self.ok,
            "errors": self.errors, "warnings": self.warnings,
            "rules": self.rules, "start": self.start, "support": self.support,
            "attempts": [{"n": a.n, "ok": a.ok, "errors": a.errors} for a in self.attempts],
        }


# --------------------------------------------------------------- prompts

_GRAMMAR_SYSTEM = (
    "You are a grammar expert. You write grammars for INPUT GENERATION, not for "
    "parsing: every rule must be able to produce concrete text. Output only the "
    "grammar, inside one fenced code block, with no commentary."
)

_GRAMMAR_RULES = """\
Write the grammar in this exact notation:
- one rule per line: <name> ::= alternative | alternative
- the root rule must be called <start>
- terminals are double-quoted: "print"
- non-terminals use angle brackets: <statement>
- the empty string is ""
- repetition is right-recursive: <list> ::= "" | <item> <list>
- do NOT use ?, *, + or parentheses
- every rule must be reachable from <start> and able to terminate
"""

_INFER_PROMPT = """\
Produce a grammar that generates inputs like these.

{rules}
Cover the structures the examples show, and no more: a grammar that generates
things the system under test has never seen is worse than a narrow one.

{description}--- EXAMPLES ---
{examples}
--- END EXAMPLES ---
"""

_REPAIR_PROMPT = """\
This grammar is rejected by the validator. Fix it and return the whole grammar.

{rules}
--- VALIDATOR ERRORS ---
{errors}
--- GRAMMAR ---
{grammar}
"""

_FANDANGO_SYSTEM = (
    "You are an expert in the Fandango grammar testing tool. You turn natural "
    "language constraints into Fandango `where` clauses. Output only the clauses, "
    "inside one fenced code block."
)
_FANDANGO_PROMPT = """\
Write Fandango `where` clauses for these constraints.

Syntax:
  where all(<condition> for <var> in *<<symbol>>)
  where all(<var> in *<<anchor>>.<NAME> for <var> in *<<usage>>.<NAME>)
Conditions are Python expressions; *<symbol> iterates derivation-tree nodes.
Only reference symbols that exist in the grammar below.

--- CONSTRAINTS ---
{constraints}
--- GRAMMAR ---
{grammar}
"""

_ISLA_SYSTEM = (
    "You are an expert in the ISLa constraint language. You turn natural language "
    "constraints into ISLa formulas. Output only the formulas, in one fenced code block."
)
_ISLA_PROMPT = """\
Write ISLa constraints for these requirements.

Syntax:
  forall <symbol> var in start: (...)
  exists <symbol> var in start: (...)
  str.len(var) > 3, str.to.int(var) < 100, var = "literal"
Only reference symbols that exist in the grammar below.

--- CONSTRAINTS ---
{constraints}
--- GRAMMAR ---
{grammar}
"""


# ------------------------------------------------------------ the gate

def _validate(text: str, generators: list[str] | None = None) -> tuple[bool, list[str], list[str], Any]:
    """Parse and diagnose a candidate exactly as a hand-written grammar."""
    try:
        grammar = parse_bnf(text)
    except GrammarError as exc:
        return False, [str(exc)], [], None
    report = diagnose(grammar)
    errors = [f"{f.code}: {f.message}" for f in report.errors]
    warnings = [f"{f.code}: {f.message}" for f in report.warnings]
    return not errors, errors, warnings, grammar


def _finish(proposal: Proposal, grammar, generators: list[str] | None) -> Proposal:
    if grammar is None:
        return proposal
    proposal.rules = len(grammar.rules)
    proposal.start = grammar.start
    for generator in generators or []:
        try:
            exp = expressibility(grammar, generator)
        except Exception:  # noqa: BLE001 - an unknown generator must not break the view
            continue
        proposal.support.append({
            "generator": generator,
            "usable": exp.usable,
            "directly": exp.directly,
            "missing": sorted(f.value for f in exp.missing),
            "blockers": exp.blockers,
            "risks": exp.risks,
        })
    return proposal


# --------------------------------------------------------------- tasks

def infer_grammar(examples: list[str], description: str = "", *,
                  generators: list[str] | None = None, **llm) -> Proposal:
    """Propose a grammar from example inputs, then validate it.

    The loop is bounded: each rejection is fed back once with the validator's
    own words, and after MAX_ATTEMPTS the best candidate is returned WITH its
    errors rather than presented as usable.
    """
    if not examples and not description.strip():
        raise LLMError("Give some example inputs, a description, or both.")

    sample = [e[:MAX_EXAMPLE_CHARS] for e in examples[:MAX_EXAMPLES]]
    prompt = _INFER_PROMPT.format(
        rules=_GRAMMAR_RULES,
        description=(f"The inputs are described as: {description.strip()}\n\n"
                     if description.strip() else ""),
        examples="\n".join(sample) if sample else "(none given; use the description)",
    )
    return _loop(_GRAMMAR_SYSTEM, prompt, "grammar", generators, **llm)


def repair_grammar(text: str, *, generators: list[str] | None = None, **llm) -> Proposal:
    """Ask for a fix to a grammar the validator rejects."""
    ok, errors, warnings, grammar = _validate(text)
    if ok:
        proposal = Proposal(kind="grammar", text=text, ok=True, warnings=warnings)
        return _finish(proposal, grammar, generators)
    prompt = _REPAIR_PROMPT.format(rules=_GRAMMAR_RULES,
                                   errors="\n".join(errors), grammar=text)
    return _loop(_GRAMMAR_SYSTEM, prompt, "grammar", generators, **llm)


def _loop(system: str, prompt: str, kind: str,
          generators: list[str] | None, **llm) -> Proposal:
    proposal = Proposal(kind=kind)
    conversation = prompt
    grammar = None
    for n in range(1, MAX_ATTEMPTS + 1):
        reply = complete(system=system, user=conversation, **llm)
        candidate = extract_code_block(reply)
        ok, errors, warnings, grammar = _validate(candidate, generators)
        proposal.attempts.append(Attempt(n=n, grammar=candidate, ok=ok, errors=errors))
        proposal.text, proposal.ok = candidate, ok
        proposal.errors, proposal.warnings = errors, warnings
        if ok:
            break
        # Hand the validator's own words back, rather than paraphrasing them.
        conversation = _REPAIR_PROMPT.format(
            rules=_GRAMMAR_RULES, errors="\n".join(errors), grammar=candidate)
    return _finish(proposal, grammar, generators)


def constraints_for(generator: str, constraints: str, grammar_text: str, **llm) -> Proposal:
    """Turn natural-language constraints into a generator's own syntax.

    Only Fandango and ISLa accept constraints at all. The result is NOT
    machine-verified the way a grammar is -- there is no constraint checker
    short of running the generator -- so it is returned explicitly unverified
    and the UI says so.
    """
    if generator not in ("fandango", "isla"):
        raise LLMError(
            f"{generator} does not take constraints. Only Fandango and ISLa do."
        )
    if not constraints.strip():
        raise LLMError("Describe the constraints you want in plain language.")

    system = _FANDANGO_SYSTEM if generator == "fandango" else _ISLA_SYSTEM
    template = _FANDANGO_PROMPT if generator == "fandango" else _ISLA_PROMPT
    reply = complete(system=system,
                     user=template.format(constraints=constraints.strip(),
                                          grammar=grammar_text),
                     **llm)
    text = extract_code_block(reply)

    proposal = Proposal(kind=f"constraints:{generator}", text=text, ok=False)
    # A weak but real check: every <symbol> mentioned must exist in the grammar.
    try:
        grammar = parse_bnf(grammar_text)
    except GrammarError:
        proposal.warnings.append("the grammar could not be parsed, so symbols were not checked")
        return proposal

    import re

    referenced = set(re.findall(r"<([A-Za-z_][A-Za-z0-9_]*)>", text))
    unknown = sorted(referenced - set(grammar.rules))
    if unknown:
        proposal.errors = [f"references a symbol the grammar does not define: <{u}>"
                           for u in unknown]
    else:
        proposal.ok = True
        proposal.warnings.append(
            "symbols check out, but constraint semantics are not verified -- "
            "run a short campaign to see whether the generator accepts them"
        )
    return proposal


def read_examples(directory: Path, limit: int = MAX_EXAMPLES) -> list[str]:
    """Example inputs from a corpus directory, for grammar inference."""
    out: list[str] = []
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        if path.name.startswith("."):
            continue
        try:
            out.append(path.read_text(errors="replace")[:MAX_EXAMPLE_CHARS])
        except OSError:
            continue
        if len(out) >= limit:
            break
    return out
