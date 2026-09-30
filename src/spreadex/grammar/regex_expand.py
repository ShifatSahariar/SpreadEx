"""Turn a regex terminal into grammar rules.

Fandango accepts `r'[A-Za-z]{3}'` directly. FuzzingBook and ISLa do not, so a
grammar using regex terminals cannot reach them unless the regex is expressed
as ordinary productions. Only the common subset is handled, and anything else
fails loudly rather than silently emitting a literal backslash-d.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ir import Alt, Lit, Node, Seq

MAX_ENUMERATED = 256   # a character class larger than this is a mistake


class RegexTooComplex(Exception):
    """The regex uses something this converter deliberately does not guess at."""


_CLASS_SHORTHAND = {
    "d": "0123456789",
    "w": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    "s": " \t",
}


@dataclass
class _Cursor:
    text: str
    pos: int = 0

    def peek(self) -> str | None:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    @property
    def done(self) -> bool:
        return self.pos >= len(self.text)


def expand_regex(pattern: str) -> Node:
    """Convert a simple regex into IR nodes. Raises RegexTooComplex otherwise."""
    cur = _Cursor(pattern)
    node = _parse_alternation(cur)
    if not cur.done:
        raise RegexTooComplex(f"unconsumed input at position {cur.pos} of {pattern!r}")
    return node


def _parse_alternation(cur: _Cursor) -> Node:
    options = [_parse_sequence(cur)]
    while cur.peek() == "|":
        cur.advance()
        options.append(_parse_sequence(cur))
    return options[0] if len(options) == 1 else Alt(tuple(options))


def _parse_sequence(cur: _Cursor) -> Node:
    items: list[Node] = []
    while not cur.done and cur.peek() not in ("|", ")"):
        items.append(_parse_quantified(cur))
    if not items:
        return Lit("")
    return items[0] if len(items) == 1 else Seq(tuple(items))


def _parse_quantified(cur: _Cursor) -> Node:
    atom = _parse_atom(cur)
    ch = cur.peek()
    if ch == "{":
        cur.advance()
        spec = ""
        while not cur.done and cur.peek() != "}":
            spec += cur.advance()
        if cur.done:
            raise RegexTooComplex("unterminated {...}")
        cur.advance()
        m = re.fullmatch(r"(\d+)(?:,(\d*))?", spec)
        if not m:
            raise RegexTooComplex(f"unsupported repetition {{{spec}}}")
        lo = int(m.group(1))
        hi = lo if m.group(2) is None else (int(m.group(2)) if m.group(2) else lo + 4)
        options = []
        for count in range(lo, hi + 1):
            if count == 0:
                options.append(Lit(""))
            elif count == 1:
                options.append(atom)
            else:
                options.append(Seq(tuple([atom] * count)))
        return options[0] if len(options) == 1 else Alt(tuple(options))
    if ch in ("*", "+", "?"):
        raise RegexTooComplex(
            f"unbounded quantifier {ch!r} in a regex terminal.\n"
            f"  Use a bounded form such as {{1,5}}, or express the repetition "
            f"as a grammar rule."
        )
    return atom


def _parse_atom(cur: _Cursor) -> Node:
    ch = cur.advance()
    if ch == "(":
        inner = _parse_alternation(cur)
        if cur.peek() != ")":
            raise RegexTooComplex("unclosed group")
        cur.advance()
        return inner
    if ch == "[":
        return _parse_class(cur)
    if ch == "\\":
        nxt = cur.advance()
        if nxt in _CLASS_SHORTHAND:
            return _chars_to_alt(_CLASS_SHORTHAND[nxt])
        return Lit(nxt)
    if ch == ".":
        raise RegexTooComplex("'.' matches too much to enumerate; use a character class")
    if ch in "*+?":
        raise RegexTooComplex(f"quantifier {ch!r} with nothing to repeat")
    return Lit(ch)


def _parse_class(cur: _Cursor) -> Node:
    negated = cur.peek() == "^"
    if negated:
        raise RegexTooComplex("negated character classes are not supported")
    chars: list[str] = []
    while not cur.done and cur.peek() != "]":
        ch = cur.advance()
        if ch == "\\":
            nxt = cur.advance()
            chars.extend(_CLASS_SHORTHAND.get(nxt, nxt))
            continue
        if cur.peek() == "-" and cur.pos + 1 < len(cur.text) and cur.text[cur.pos + 1] != "]":
            cur.advance()
            end = cur.advance()
            if ord(end) < ord(ch):
                raise RegexTooComplex(f"reversed range {ch}-{end}")
            chars.extend(chr(c) for c in range(ord(ch), ord(end) + 1))
            continue
        chars.append(ch)
    if cur.done:
        raise RegexTooComplex("unterminated character class")
    cur.advance()
    return _chars_to_alt(chars)


def _chars_to_alt(chars) -> Node:
    unique = list(dict.fromkeys(chars))
    if not unique:
        raise RegexTooComplex("empty character class")
    if len(unique) > MAX_ENUMERATED:
        raise RegexTooComplex(f"character class of {len(unique)} characters is too large to enumerate")
    if len(unique) == 1:
        return Lit(unique[0])
    return Alt(tuple(Lit(c) for c in unique))
