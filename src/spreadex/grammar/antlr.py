"""Read and write ANTLRv4 grammars.

ANTLR matters for two reasons: it is the notation the public grammar zoo is
written in, and it is the only notation Grammarinator consumes. Supporting it
turns "write a grammar for each generator" into "bring the grammar you already
have".

For GENERATION the lexer/parser split does not exist: a lexer rule is simply a
rule that produces text. So both kinds land in one namespace, and `fragment` is
just another rule.

Constructs that cannot be generated from are reported rather than guessed at.
`.` and `~[...]` match sets defined by exclusion, which is meaningful when
parsing and unbounded when generating, so they expand against a documented
printable alphabet and say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ir import Alt, Grammar, Lit, Node, Ref, Repeat, Seq
from .parse import GrammarError

#: The alphabet `.` and `~[...]` expand against when generating. Printable
#: ASCII minus the quote characters, which keeps generated text quotable.
DEFAULT_ALPHABET = "".join(
    chr(c) for c in range(32, 127) if chr(c) not in "'\"\\"
)

_HEADER = re.compile(r"^\s*(lexer\s+|parser\s+)?grammar\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.M)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
            "\\": "\\", "'": "'", '"': '"', "-": "-", "]": "]", "0": "\0"}


@dataclass
class AntlrNotes:
    """What was ignored or approximated while reading a grammar."""

    name: str = ""
    ignored_actions: int = 0
    ignored_predicates: int = 0
    skipped_rules: list[str] = field(default_factory=list)
    approximated: list[str] = field(default_factory=list)

    def as_findings(self):
        from .diagnose import Finding, Severity

        out = []
        if self.ignored_actions:
            out.append(Finding(Severity.INFO, "antlr-actions",
                               f"{self.ignored_actions} target-language action(s) ignored",
                               fix="actions cannot run during generation; they are dropped"))
        if self.ignored_predicates:
            out.append(Finding(Severity.WARNING, "antlr-predicates",
                               f"{self.ignored_predicates} semantic predicate(s) ignored",
                               fix="generated inputs may violate the conditions these enforce"))
        for rule in self.skipped_rules:
            out.append(Finding(Severity.WARNING, "antlr-skip",
                               f"<{rule}> is a `-> skip` lexer rule", rule=rule,
                               fix="it still generates text; remove it if that is wrong"))
        for note in self.approximated:
            out.append(Finding(Severity.INFO, "antlr-approximated", note))
        return out


# --------------------------------------------------------------- tokenizing

def _skip_balanced(text: str, i: int, open_ch: str, close_ch: str,
                   code: bool = True) -> int:
    """Index just past a balanced {...} or (...).

    Action blocks contain target-language code, so the scanner has to know
    about that language's strings AND comments. A Python comment reading
    "the outer loop's update" is enough to break a scanner that only tracks
    quotes: the lone apostrophe opens a string that swallows the closing brace.
    """
    depth = 0
    n = len(text)
    start = i
    while i < n:
        ch = text[i]

        if code and ch == "#":                      # Python / Ruby comment
            while i < n and text[i] != "\n":
                i += 1
            continue
        if code and ch == "/" and i + 1 < n:        # C-family comments
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                nxt = text.find("*/", i + 2)
                i = n if nxt == -1 else nxt + 2
                continue

        if ch in "'\"":
            triple = text[i:i + 3]
            if code and triple in ("\'\'\'", '\"\"\"'):
                nxt = text.find(triple, i + 3)
                i = n if nxt == -1 else nxt + 3
                continue
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote or text[i] == "\n":
                    break                            # unterminated: do not run on
                i += 1
            i += 1
            continue

        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    line = text.count("\n", 0, start) + 1
    raise GrammarError(f"line {line}: unbalanced {open_ch!r}")


def strip_comments(text: str) -> str:
    """Blank grammar comments and the INTERIOR of every action block.

    Action blocks hold target-language code whose comments and strings follow
    that language's rules, not ANTLR's. Rather than teach every later pass
    about Python and Java lexing, the interior is replaced with spaces once,
    here. Braces and newlines are preserved so brace matching and line numbers
    downstream still work, and actions are discarded anyway.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        if ch == "'":                       # an ANTLR literal: keep verbatim
            out.append(ch)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == "'":
                    i += 1
                    break
                i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            stop = n if end == -1 else end + 2
            out.append("\n" * text.count("\n", i, stop))
            i = stop
            continue

        if ch == "{":                       # an action block
            stop = _skip_balanced(text, i, "{", "}", code=True)
            interior = text[i + 1:stop - 1]
            out.append("{")
            out.append("\n" * interior.count("\n"))
            out.append("}")
            i = stop
            continue

        out.append(ch)
        i += 1
    return "".join(out)


class _AntlrParser:
    def __init__(self, text: str) -> None:
        self.text = strip_comments(text)
        self.pos = 0
        self.notes = AntlrNotes()

    # -------------------------------------------------------------- helpers

    def ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def line(self) -> int:
        return self.text.count("\n", 0, self.pos) + 1

    def at(self, literal: str) -> bool:
        return self.text.startswith(literal, self.pos)

    # ---------------------------------------------------------------- top

    def parse(self) -> tuple[dict[str, Node], AntlrNotes]:
        m = _HEADER.search(self.text)
        if m:
            self.notes.name = m.group(2)
            self.pos = m.end()

        rules: dict[str, Node] = {}
        while True:
            self.ws()
            if self.pos >= len(self.text):
                break
            if self.skip_preamble():
                continue
            name, body, is_skip = self.parse_rule()
            if is_skip:
                self.notes.skipped_rules.append(name)
            if name in rules:
                left = list(rules[name].options) if isinstance(rules[name], Alt) else [rules[name]]
                right = list(body.options) if isinstance(body, Alt) else [body]
                rules[name] = Alt(tuple(left + right))
            else:
                rules[name] = body
        if not rules:
            raise GrammarError(
                "No rules found in the ANTLR grammar.\n"
                "  Expected rules of the form:  name : alternative | alternative ;"
            )
        return rules, self.notes

    def skip_preamble(self) -> bool:
        """options{}, tokens{}, @header{}, import x; and mode declarations."""
        for keyword in ("options", "tokens", "channels"):
            if self.at(keyword):
                save = self.pos
                self.pos += len(keyword)
                self.ws()
                if self.at("{"):
                    self.pos = _skip_balanced(self.text, self.pos, "{", "}")
                    return True
                self.pos = save
        if self.at("@"):
            brace = self.text.find("{", self.pos)
            if brace == -1:
                raise GrammarError(f"line {self.line()}: '@' block without a body")
            self.pos = _skip_balanced(self.text, brace, "{", "}")
            self.notes.ignored_actions += 1
            return True
        if self.at("import"):
            end = self.text.find(";", self.pos)
            self.pos = len(self.text) if end == -1 else end + 1
            self.notes.approximated.append(
                "an `import` was ignored; imported rules are not available"
            )
            return True
        if self.at("mode "):
            end = self.text.find(";", self.pos)
            self.pos = len(self.text) if end == -1 else end + 1
            self.notes.approximated.append("lexer `mode` declarations are ignored")
            return True
        return False

    def parse_rule(self) -> tuple[str, Node, bool]:
        self.ws()
        if self.at("fragment"):
            self.pos += len("fragment")
            self.ws()
        m = _IDENT.match(self.text, self.pos)
        if not m:
            raise GrammarError(
                f"line {self.line()}: expected a rule name, found "
                f"{self.text[self.pos:self.pos + 20]!r}"
            )
        name = m.group(0)
        self.pos = m.end()
        self.ws()
        # Rule-level [args] / returns / locals / options are parsing concerns.
        while self.pos < len(self.text) and self.text[self.pos] in "[":
            self.pos = _skip_balanced(self.text, self.pos, "[", "]", code=False)
            self.ws()
        for keyword in ("returns", "locals", "throws"):
            if self.at(keyword):
                self.pos += len(keyword)
                self.ws()
                if self.at("["):
                    self.pos = _skip_balanced(self.text, self.pos, "[", "]", code=False)
                self.ws()
        if self.at("options"):
            self.pos += len("options")
            self.ws()
            if self.at("{"):
                self.pos = _skip_balanced(self.text, self.pos, "{", "}")
            self.ws()
        # Rule-level actions: `rule @init {...} @after {...} : ...`
        while self.at("@"):
            brace = self.text.find("{", self.pos)
            if brace == -1:
                raise GrammarError(f"line {self.line()}: '@' block without a body")
            self.pos = _skip_balanced(self.text, brace, "{", "}")
            self.notes.ignored_actions += 1
            self.ws()
        if not self.at(":"):
            raise GrammarError(
                f"line {self.line()}: expected ':' after rule {name!r}, found "
                f"{self.text[self.pos:self.pos + 20]!r}"
            )
        self.pos += 1
        body, is_skip = self.parse_alternatives(top=True)
        self.ws()
        if self.at(";"):
            self.pos += 1
        return name, body, is_skip

    def parse_alternatives(self, top: bool = False) -> tuple[Node, bool]:
        options: list[Node] = []
        is_skip = False
        while True:
            node, skip = self.parse_sequence()
            is_skip = is_skip or skip
            options.append(node)
            self.ws()
            if self.at("|"):
                self.pos += 1
                continue
            break
        node = options[0] if len(options) == 1 else Alt(tuple(options))
        return node, is_skip

    def parse_sequence(self) -> tuple[Node, bool]:
        items: list[Node] = []
        is_skip = False
        while True:
            self.ws()
            if self.pos >= len(self.text):
                break
            ch = self.text[self.pos]
            if ch in "|;)":
                break
            if self.at("->"):
                # lexer commands: skip, channel(...), type(...), more, mode(...)
                self.pos += 2
                end = self.pos
                while end < len(self.text) and self.text[end] not in ";|":
                    end += 1
                command = self.text[self.pos:end]
                if "skip" in command:
                    is_skip = True
                self.pos = end
                continue
            if ch == "#":
                # an alternative label; irrelevant to generation
                self.pos += 1
                self.ws()
                m = _IDENT.match(self.text, self.pos)
                if m:
                    self.pos = m.end()
                continue
            if ch == "{":
                end = _skip_balanced(self.text, self.pos, "{", "}")
                self.pos = end
                if self.pos < len(self.text) and self.text[self.pos] == "?":
                    self.pos += 1
                    self.notes.ignored_predicates += 1
                else:
                    self.notes.ignored_actions += 1
                continue
            items.append(self.parse_postfix())
        if not items:
            return Lit(""), is_skip
        node = items[0] if len(items) == 1 else Seq(tuple(items))
        return node, is_skip

    def parse_postfix(self) -> Node:
        node = self.parse_atom()
        while self.pos < len(self.text) and self.text[self.pos] in "?*+":
            op = self.text[self.pos]
            self.pos += 1
            # Non-greedy suffixes change parsing, not the language.
            if self.pos < len(self.text) and self.text[self.pos] == "?":
                self.pos += 1
            lo, hi = {"?": (0, 1), "*": (0, None), "+": (1, None)}[op]
            node = Repeat(node, lo, hi)
        return node

    def parse_atom(self) -> Node:
        self.ws()
        ch = self.text[self.pos]

        if ch == "(":
            self.pos += 1
            node, _ = self.parse_alternatives()
            self.ws()
            if not self.at(")"):
                raise GrammarError(f"line {self.line()}: unclosed '(' in a rule body")
            self.pos += 1
            return node

        if ch == "'":
            return Lit(self.read_literal())

        if ch == "[":
            return self.read_charset(negated=False)

        if ch == "~":
            self.pos += 1
            self.ws()
            if self.at("["):
                return self.read_charset(negated=True)
            if self.at("'"):
                excluded = self.read_literal()
                return self._alphabet_minus(set(excluded), f"~'{excluded}'")
            raise GrammarError(f"line {self.line()}: '~' must be followed by a set or a literal")

        if ch == ".":
            self.pos += 1
            return self._alphabet_minus(set(), ".")

        m = _IDENT.match(self.text, self.pos)
        if m:
            name = m.group(0)
            self.pos = m.end()
            self.ws()
            # a label: `x=atom` or `x+=atom`
            if self.at("+="):
                self.pos += 2
                return self.parse_atom()
            if self.at("=") and not self.at("=="):
                self.pos += 1
                return self.parse_atom()
            if name == "EOF":
                return Lit("")
            return Ref(name)

        raise GrammarError(
            f"line {self.line()}: unexpected {ch!r} in a rule body "
            f"({self.text[self.pos:self.pos + 24]!r})"
        )

    # ------------------------------------------------------------ terminals

    def read_literal(self) -> str:
        self.pos += 1   # opening quote
        out: list[str] = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                nxt = self.text[self.pos]
                if nxt == "u":
                    hexdigits = self.text[self.pos + 1:self.pos + 5]
                    out.append(chr(int(hexdigits, 16)))
                    self.pos += 5
                    continue
                out.append(_ESCAPES.get(nxt, nxt))
                self.pos += 1
                continue
            if ch == "'":
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1
        raise GrammarError(f"line {self.line()}: unterminated literal")

    def read_charset(self, negated: bool) -> Node:
        start = self.pos
        self.pos += 1   # '['
        chars: list[str] = []
        while self.pos < len(self.text) and self.text[self.pos] != "]":
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                nxt = self.text[self.pos]
                if nxt == "u":
                    ch = chr(int(self.text[self.pos + 1:self.pos + 5], 16))
                    self.pos += 5
                else:
                    ch = _ESCAPES.get(nxt, nxt)
                    self.pos += 1
            else:
                self.pos += 1
            if (self.pos < len(self.text) and self.text[self.pos] == "-"
                    and self.pos + 1 < len(self.text) and self.text[self.pos + 1] != "]"):
                self.pos += 1
                end_ch = self.text[self.pos]
                if end_ch == "\\":
                    self.pos += 1
                    end_ch = _ESCAPES.get(self.text[self.pos], self.text[self.pos])
                self.pos += 1
                chars.extend(chr(c) for c in range(ord(ch), ord(end_ch) + 1))
                continue
            chars.append(ch)
        if self.pos >= len(self.text):
            raise GrammarError(f"line {self.line()}: unterminated character set")
        self.pos += 1   # ']'
        raw = self.text[start:self.pos]
        if negated:
            return self._alphabet_minus(set(chars), f"~{raw}")
        unique = list(dict.fromkeys(chars))
        if not unique:
            raise GrammarError(f"line {self.line()}: empty character set {raw}")
        if len(unique) == 1:
            return Lit(unique[0])
        return Alt(tuple(Lit(c) for c in unique))

    def _alphabet_minus(self, excluded: set[str], shown: str) -> Node:
        """`.` and `~[...]` describe sets by exclusion, which is unbounded.

        Parsing can afford that; generating cannot, so they expand against a
        documented printable alphabet. Recorded so the user is told.
        """
        allowed = [c for c in DEFAULT_ALPHABET if c not in excluded]
        note = (f"{shown} expanded to {len(allowed)} printable characters; "
                f"generation needs a bounded alphabet")
        if note not in self.notes.approximated:
            self.notes.approximated.append(note)
        return Alt(tuple(Lit(c) for c in allowed))


def parse_antlr(text: str, source_path: str | None = None,
                start: str | None = None) -> tuple[Grammar, AntlrNotes]:
    """Parse an ANTLRv4 grammar into the IR, with notes on what was ignored."""
    parser = _AntlrParser(text)
    rules, notes = parser.parse()
    chosen = (start or "").strip("<>")
    if not chosen:
        chosen = "start" if "start" in rules else next(iter(rules))
    return Grammar(chosen, rules, "antlr", source_path), notes


# ------------------------------------------------------------------ rendering

_RESERVED = {"grammar", "lexer", "parser", "fragment", "options", "tokens",
             "import", "mode", "channels", "returns", "locals", "throws", "EOF"}


def antlr_rule_name(name: str, taken: dict[str, str]) -> str:
    """Map an IR rule name to a valid ANTLR *parser* rule name.

    Everything becomes a parser rule (lowercase initial) so that terminals stay
    inline literals and ANTLR's lexer/parser separation rules cannot be
    violated by a grammar that was never written with them in mind.
    """
    if name in taken:
        return taken[name]
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "r_" + cleaned
    # ALL_CAPS names (ANTLR lexer-rule spelling) read badly as `iDENT_NUM`,
    # so lowercase them whole; mixed case only needs its initial lowered.
    stripped = cleaned.replace("_", "")
    cleaned = cleaned.lower() if stripped.isupper() else cleaned[0].lower() + cleaned[1:]
    if cleaned in _RESERVED:
        cleaned += "_"
    candidate = cleaned
    suffix = 2
    used = set(taken.values())
    while candidate in used:
        candidate = f"{cleaned}{suffix}"
        suffix += 1
    taken[name] = candidate
    return candidate


def escape_antlr_literal(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)
