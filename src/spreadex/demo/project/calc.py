#!/usr/bin/env python3
"""A tiny expression evaluator, used as SpreadEx's demo system under test.

It is deliberately small enough to read in one sitting, and it behaves the way
a real parser behaves, which is what makes the demo honest:

  * valid input          -> prints the value, exits 0
  * input it cannot read -> prints `calc: SyntaxError: ...` on stderr, exits 1
    This is the system WORKING. A campaign that reported these as crashes
    would be reporting noise, and the Testing Strategy step exists to say so.
  * one genuine defect   -> see below

The defect is real, reachable, and documented rather than hidden, because a
demo that cannot fail teaches nothing and a demo that always "finds a bug" by
sleight of hand is worse.

The defect: division by zero is guarded, and the guard was never extended to
the remainder operator beside it. `1 / 0` is reported cleanly; `1 % 0` dies
with an uncaught ZeroDivisionError and a traceback. An incomplete guard that
covers one operator and not its sibling is one of the most common real bugs
there is, and it is exactly what a generator working through the operator
space stumbles into.

Whether a given campaign reaches it depends on what the generators produce
under the budget. If a run finds nothing, SpreadEx says so.
"""

from __future__ import annotations

import sys

#: calc.py models a parser with a modest stack budget -- an embedded
#: interpreter, a sandboxed runtime, a thread with a small stack. The number is
#: small so the demo runs on a laptop in seconds; the defect is not the size of
#: the budget, it is that exceeding it crashes instead of being reported.


class SyntaxErr(Exception):
    """The input was not a well-formed expression. Not a bug: an answer."""


# ----------------------------------------------------------------- lexing

def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            tokens.append(text[i:j])
            i = j
        elif c in "+-*/%()":
            tokens.append(c)
            i += 1
        else:
            raise SyntaxErr(f"unexpected character {c!r} at offset {i}")
    return tokens


# ---------------------------------------------------------------- parsing

class Parser:
    """Recursive descent: expr -> term (('+'|'-') term)*, and so on down."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise SyntaxErr("input ended in the middle of an expression")
        self.pos += 1
        return tok

    def expr(self) -> float:
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            value = value + right if op == "+" else value - right
        return value

    def term(self) -> float:
        value = self.atom()
        while self.peek() in ("*", "/", "%"):
            op = self.take()
            right = self.atom()
            if op == "/" and right == 0:
                raise SyntaxErr("division by zero")
            # THE DEFECT: `%` is missing from that guard, so `1 % 0` reaches
            # Python's own ZeroDivisionError and crashes instead of being
            # reported the way `1 / 0` is. Left exactly as written.
            value = value * right if op == "*" else (
                value / right if op == "/" else value % right)
        return value

    def atom(self) -> float:
        tok = self.take()
        if tok == "-":
            return -self.atom()
        if tok == "(":
            value = self.expr()
            if self.take() != ")":
                raise SyntaxErr("expected a closing parenthesis")
            return value
        try:
            return float(tok)
        except ValueError:
            raise SyntaxErr(f"expected a number, found {tok!r}") from None


def evaluate(text: str) -> float:
    parser = Parser(tokenize(text))
    value = parser.expr()
    if parser.peek() is not None:
        raise SyntaxErr(f"trailing input: {parser.peek()!r}")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: calc.py FILE", file=sys.stderr)
        return 2
    try:
        text = open(argv[1], encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"calc: cannot read input: {exc}", file=sys.stderr)
        return 2
    try:
        print(evaluate(text))
    except SyntaxErr as exc:
        # The system working as designed. The campaign is told to expect it.
        print(f"calc: SyntaxError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
