"""Read a grammar into the IR.

A line-based splitter is not enough: `"(" <expr> ")"` uses parentheses as
terminal text while `(", " <item>)*` uses them as grouping, and only a tokenizer
that understands quoting can tell those apart. The research prototype's
line-based parser had to disable its own reachability check for Fandango
grammars precisely because grouping defeated it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .ir import Alt, Grammar, Lit, Node, Ref, Regex, Repeat, Seq


class GrammarError(Exception):
    """A grammar problem, with the location that caused it."""


@dataclass
class Token:
    kind: str          # nonterminal | string | regex | bar | lparen | rparen | repeat | define | newline | eof
    value: str
    line: int
    min: int = 0
    max: int | None = None


_DEFINE = re.compile(r"::=|(?<![-<>=!])->")
_NONTERMINAL = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")
_REPEAT = re.compile(r"\{\s*(\d+)\s*(?:,\s*(\d*)\s*)?\}")
_IDENT_ONLY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        tokens.extend(_tokenize_line(line, lineno))
        tokens.append(Token("newline", "", lineno))
    tokens.append(Token("eof", "", len(text.splitlines()) + 1))
    return tokens


def _strip_comment(line: str) -> str:
    """Drop a trailing `#` comment without touching a `#` inside a string."""
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _tokenize_line(line: str, lineno: int) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch.isspace():
            i += 1
            continue

        m = _DEFINE.match(line, i)
        if m:
            tokens.append(Token("define", m.group(0), lineno))
            i = m.end()
            continue

        if ch == "|":
            tokens.append(Token("bar", "|", lineno))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token("lparen", "(", lineno))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("rparen", ")", lineno))
            i += 1
            continue

        if ch in "?*+":
            lo, hi = {"?": (0, 1), "*": (0, None), "+": (1, None)}[ch]
            tokens.append(Token("repeat", ch, lineno, lo, hi))
            i += 1
            continue

        m = _REPEAT.match(line, i)
        if m:
            lo = int(m.group(1))
            hi_raw = m.group(2)
            if hi_raw is None:
                hi = lo                      # {n} means exactly n
            elif hi_raw == "":
                hi = None                    # {n,} means n or more
            else:
                hi = int(hi_raw)
            if hi is not None and hi < lo:
                raise GrammarError(f"line {lineno}: repetition {{{lo},{hi}}} has max below min")
            tokens.append(Token("repeat", m.group(0), lineno, lo, hi))
            i = m.end()
            continue

        m = _NONTERMINAL.match(line, i)
        if m:
            tokens.append(Token("nonterminal", m.group(1), lineno))
            i = m.end()
            continue

        # r'...' / r"..." regex terminal
        if ch == "r" and i + 1 < n and line[i + 1] in "\"'":
            value, i = _read_quoted(line, i + 1, lineno)
            tokens.append(Token("regex", value, lineno))
            continue

        if ch in "\"'":
            value, i = _read_quoted(line, i, lineno)
            tokens.append(Token("string", value, lineno))
            continue

        # A bare identifier followed by ::= is a missing pair of angle
        # brackets, which is a much more likely mistake than an unquoted
        # terminal -- say so rather than making the user guess.
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", line[i:])
        if m and _DEFINE.search(line, i + m.end()):
            name = m.group(0)
            raise GrammarError(
                f"line {lineno}: expected a rule name like <{name}>, found a bare {name}.\n"
                f"  Fix: write <{name}> ::= ..."
            )
        raise GrammarError(
            f"line {lineno}: unexpected character {ch!r}.\n"
            f"  Terminals must be quoted: write \"{ch}\" rather than a bare {ch}."
        )
    return tokens


def _read_quoted(line: str, start: int, lineno: int) -> tuple[str, int]:
    quote = line[start]
    out: list[str] = []
    i = start + 1
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            nxt = line[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                        '"': '"', "'": "'"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise GrammarError(f"line {lineno}: unterminated string starting at column {start + 1}")


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def skip_newlines(self) -> None:
        while self.current.kind == "newline":
            self.advance()

    def parse_grammar(self) -> dict[str, Node]:
        rules: dict[str, Node] = {}
        order: list[str] = []
        self.skip_newlines()
        while self.current.kind != "eof":
            name, body = self.parse_rule()
            if name in rules:
                # A repeated head means more alternatives for the same rule.
                existing = rules[name]
                left = list(existing.options) if isinstance(existing, Alt) else [existing]
                right = list(body.options) if isinstance(body, Alt) else [body]
                rules[name] = Alt(tuple(left + right))
            else:
                rules[name] = body
                order.append(name)
            self.skip_newlines()
        return rules

    def parse_rule(self) -> tuple[str, Node]:
        tok = self.current
        if tok.kind != "nonterminal":
            raise GrammarError(
                f"line {tok.line}: expected a rule name like <name>, found {tok.value or tok.kind!r}."
            )
        name = self.advance().value
        if self.current.kind != "define":
            raise GrammarError(
                f"line {self.current.line}: expected '::=' after <{name}>."
            )
        self.advance()
        body = self.parse_alternation(top_level=True)
        return name, body

    def parse_alternation(self, top_level: bool = False) -> Node:
        options = [self.parse_sequence(top_level)]
        while True:
            if self.current.kind == "bar":
                self.advance()
                options.append(self.parse_sequence(top_level))
                continue
            # A rule may continue on the next line, either with a leading '|'
            # or as an indented continuation of the sequence.
            if top_level and self.current.kind == "newline":
                save = self.pos
                self.skip_newlines()
                if self.current.kind == "bar":
                    self.advance()
                    options.append(self.parse_sequence(top_level))
                    continue
                self.pos = save
            break
        return options[0] if len(options) == 1 else Alt(tuple(options))

    def parse_sequence(self, top_level: bool = False) -> Node:
        items: list[Node] = []
        while True:
            kind = self.current.kind
            if kind in ("bar", "rparen", "eof"):
                break
            if kind == "newline":
                if not top_level:
                    self.advance()
                    continue
                # Continue onto the next line only when it is clearly a
                # continuation -- not the head of the next rule.
                save = self.pos
                self.skip_newlines()
                if self._starts_new_rule():
                    self.pos = save
                    break
                if self.current.kind == "bar":
                    self.pos = save
                    break
                continue
            items.append(self.parse_postfix())
        if not items:
            return Lit("")
        return items[0] if len(items) == 1 else Seq(tuple(items))

    def _starts_new_rule(self) -> bool:
        return (self.current.kind == "nonterminal"
                and self.tokens[self.pos + 1].kind == "define")

    def parse_postfix(self) -> Node:
        node = self.parse_atom()
        while self.current.kind == "repeat":
            tok = self.advance()
            node = Repeat(node, tok.min, tok.max)
        return node

    def parse_atom(self) -> Node:
        tok = self.advance()
        if tok.kind == "nonterminal":
            return Ref(tok.value)
        if tok.kind == "string":
            return Lit(tok.value)
        if tok.kind == "regex":
            return Regex(tok.value)
        if tok.kind == "lparen":
            inner = self.parse_alternation()
            if self.current.kind != "rparen":
                raise GrammarError(f"line {tok.line}: unclosed '(' ")
            self.advance()
            return inner
        raise GrammarError(
            f"line {tok.line}: unexpected {tok.kind} {tok.value!r} in a rule body."
        )


def parse_bnf(text: str, source_format: str = "bnf", start: str | None = None,
              source_path: str | None = None) -> Grammar:
    """Parse BNF/EBNF (`::=` or `->`), including grouping and repetition."""
    rules = _Parser(tokenize(text)).parse_grammar()
    if not rules:
        raise GrammarError(
            "No rules found.\n"
            "  Expected lines of the form:  <name> ::= <other> \"literal\""
        )
    chosen = (start or "").strip("<>") or ("start" if "start" in rules else next(iter(rules)))
    return Grammar(chosen, rules, source_format, source_path)


# --------------------------------------------------------------- fuzzingbook

def parse_fuzzingbook(text: str, source_path: str | None = None) -> Grammar:
    """Parse a FuzzingBook grammar dict out of a Python module.

    Accepts `GRAMMAR = {...}`, `grammar = {...}`, or a `get_*_grammar()`
    function returning a dict literal. The module is NOT executed: the dict is
    read from the AST, because a grammar file is data and running it would be an
    arbitrary-code path through something a user was told was a grammar.
    """
    tree = ast.parse(text)
    raw = _find_dict(tree)
    if raw is None:
        raise GrammarError(
            "No grammar dict found.\n"
            "  Expected `GRAMMAR = {...}`, `grammar = {...}`, or a "
            "`get_*_grammar()` returning a dict literal."
        )

    rules: dict[str, Node] = {}
    for key, alternatives in raw.items():
        name = str(key).strip("<>")
        options = [_parse_fuzzingbook_alt(a) for a in alternatives]
        rules[name] = options[0] if len(options) == 1 else Alt(tuple(options))
    start = "start" if "start" in rules else next(iter(rules))
    return Grammar(start, rules, "fuzzingbook", source_path)


def _parse_fuzzingbook_alt(alt: str) -> Node:
    """A FuzzingBook alternative is a string mixing literals and <refs>."""
    items: list[Node] = []
    pos = 0
    for m in _NONTERMINAL.finditer(alt):
        if m.start() > pos:
            items.append(Lit(alt[pos:m.start()]))
        items.append(Ref(m.group(1)))
        pos = m.end()
    if pos < len(alt):
        items.append(Lit(alt[pos:]))
    if not items:
        return Lit("")
    return items[0] if len(items) == 1 else Seq(tuple(items))


def _find_dict(tree: ast.Module) -> dict | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.lower() in ("grammar", "grammar_def"):
                    value = _literal(node.value)
                    if isinstance(value, dict):
                        return value
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("get_"):
            local: dict[str, object] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                    local[stmt.targets[0].id] = _literal(stmt.value)
                if isinstance(stmt, ast.Return):
                    if isinstance(stmt.value, ast.Name):
                        candidate = local.get(stmt.value.id)
                    else:
                        candidate = _literal(stmt.value)
                    if isinstance(candidate, dict):
                        return candidate
    return None


def _literal(node: ast.AST) -> object:
    """literal_eval, plus the two FuzzingBook helpers that appear in practice."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        pass
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "crange":
        try:
            lo, hi = ast.literal_eval(node.args[0]), ast.literal_eval(node.args[1])
            return [chr(c) for c in range(ord(lo), ord(hi) + 1)]
        except (ValueError, SyntaxError, IndexError):
            return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        return None
    if isinstance(node, ast.Dict):
        out = {}
        for k, v in zip(node.keys, node.values):
            key = _literal(k)
            val = _literal(v)
            if key is None or val is None:
                return None
            out[key] = val
        return out
    if isinstance(node, ast.List):
        items = [_literal(e) for e in node.elts]
        return None if any(i is None for i in items) else items
    if isinstance(node, ast.ListComp):
        return None
    return None


def load(path: str | Path, start: str | None = None) -> Grammar:
    """Parse a grammar file, choosing the front end from its extension."""
    path = Path(path)
    text = path.read_text()
    suffix = path.suffix.lower()
    if suffix == ".py":
        return parse_fuzzingbook(text, source_path=str(path))
    if suffix == ".g4":
        from .antlr import parse_antlr
        return parse_antlr(text, source_path=str(path), start=start)[0]
    fmt = {".fan": "fandango", ".bnf": "bnf", ".isla": "isla", ".ebnf": "ebnf"}.get(suffix, "bnf")
    return parse_bnf(text, source_format=fmt, start=start, source_path=str(path))
