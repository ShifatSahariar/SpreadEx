"""Drive each generator in its own environment and collect what it produced.

Every adapter runs the generator as a SUBPROCESS. SpreadEx never imports a
generator: ISLa is GPL-3.0, Fandango is EUPL-1.2, and their dependency pins
conflict with each other. A subprocess boundary keeps the core permissively
licensed and keeps one generator's dependency hell out of the others'.

Adding a generator means adding a catalog entry and an adapter function. It
does not mean touching the campaign, the corpus or the oracle.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .manager import GeneratorError, GeneratorManager

# Generated inputs larger than this are almost always a runaway recursion in
# the grammar rather than something a SUT should be asked to parse.
MAX_INPUT_BYTES = 1 << 20


@dataclass
class GeneratedBatch:
    generator: str
    inputs: list[bytes]
    elapsed_ms: float
    #: Set when the generator ran out of budget but had already produced work.
    partial: bool = False

    @property
    def cost_per_input_ms(self) -> float:
        return self.elapsed_ms / max(1, len(self.inputs))


def _collect(out_dir: Path, suffixes=(".txt", ".js", ".input", "")) -> list[bytes]:
    found = []
    for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
        if suffixes and path.suffix not in suffixes:
            continue
        data = path.read_bytes()
        if 0 < len(data) <= MAX_INPUT_BYTES:
            found.append(data)
    return found


def _run(cmd: list[str], timeout: float, what: str) -> subprocess.CompletedProcess:
    # Every generator runs in Python. A fixed hash seed is what makes a seeded generator actually
    # reproducible: without it, set and dict iteration order changes from process to process
    # (Fandango 1.3 gave different inputs for the same --random-seed until this was pinned).
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired:
        # Deliberately mode-agnostic: under `generation.mode: time` the budget
        # IS the point and "lower generation.count" is advice for a setting
        # that does not exist there.
        raise GeneratorError(
            f"{what} exceeded its generation budget ({timeout:.0f}s) and wrote "
            f"nothing usable.\n"
            f"  Fix: give it longer (budget.generation, or "
            f"generation.per_generator under mode: time),\n"
            f"       ask for fewer inputs (generation.count under mode: count), "
            f"or simplify the grammar."
        ) from None
    except OSError as exc:
        raise GeneratorError(f"{what} could not be started: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode(errors="replace").strip()[-2000:]
        raise GeneratorError(f"{what} failed (exit {proc.returncode}).\n{err}")
    return proc


# --------------------------------------------------------------- fuzzingbook

_FUZZINGBOOK_DRIVER = r'''
import importlib.util, json, sys, random
grammar_path, out_dir, n, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
random.seed(seed)

spec = importlib.util.spec_from_file_location("_spreadex_grammar", grammar_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# The research grammars expose a get_<name>_grammar() factory; plain GRAMMAR or
# grammar dicts are also accepted.
grammar = None
for attr in ("GRAMMAR", "grammar"):
    if isinstance(getattr(mod, attr, None), dict):
        grammar = getattr(mod, attr)
        break
if grammar is None:
    for name in dir(mod):
        if name.startswith("get_") and name.endswith("_grammar") and callable(getattr(mod, name)):
            grammar = getattr(mod, name)()
            break
if grammar is None:
    raise SystemExit("no grammar found: expected GRAMMAR, grammar, or get_*_grammar()")

from fuzzingbook.Grammars import convert_ebnf_grammar, is_valid_grammar
from fuzzingbook.ProbabilisticGrammarFuzzer import ProbabilisticGrammarFuzzer

# convert_ebnf_grammar reads a '+', '*' or '?' that merely FOLLOWS a
# <nonterminal> as an operator, so a JavaScript '<identifier>++;' becomes
# "one or more identifiers, then +;" -- a different language, and an
# unbounded one. A grammar SpreadEx emitted is already plain BNF, so the
# conversion is skipped for it.
if getattr(mod, "SPREADEX_PURE_BNF", False):
    converted = grammar
else:
    converted = convert_ebnf_grammar(grammar)
if not is_valid_grammar(converted):
    raise SystemExit("grammar is not valid after EBNF conversion")

fuzzer = ProbabilisticGrammarFuzzer(converted)
import os
os.makedirs(out_dir, exist_ok=True)
written = 0
for i in range(n):
    try:
        text = fuzzer.fuzz()
    except RecursionError:
        continue   # a runaway derivation, not a usable input
    with open(os.path.join(out_dir, "fuzz_%05d.txt" % i), "w") as fh:
        fh.write(text)
    written += 1
print(json.dumps({"written": written}))
'''


def generate_fuzzingbook(mgr, grammar: Path, n: int, out_dir: Path, seed: int, timeout: float):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(_FUZZINGBOOK_DRIVER)
        driver = fh.name
    try:
        _run([mgr.python_for("fuzzingbook"), driver, str(grammar), str(out_dir), str(n), str(seed)],
             timeout, "FuzzingBook")
    finally:
        Path(driver).unlink(missing_ok=True)
    return _collect(out_dir)


# ------------------------------------------------------------------ fandango

def generate_fandango(mgr, grammar: Path, n: int, out_dir: Path, seed: int, timeout: float):
    exe = mgr.executable_for("fandango", "fandango")
    if not exe:
        raise GeneratorError(
            "Fandango is not installed.\n  Fix: spreadex generators install fandango"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([exe, "fuzz", "-f", str(grammar), "-n", str(n), "-d", str(out_dir), "--random-seed", str(seed)],
         timeout, "Fandango")
    return _collect(out_dir)


# ---------------------------------------------------------------------- isla

def generate_isla(mgr, grammar: Path, n: int, out_dir: Path, seed: int, timeout: float):
    """Drive `isla solve`, as the research pipeline does.

    The Python API caps output at `max_number_free_instantiations=10` by
    default, so calling `solve()` in a loop silently returns 10 inputs however
    many were asked for. The CLI takes the count directly and is what the
    research code uses, so the adapter uses it too.
    """
    exe = mgr.executable_for("isla", "isla")
    if not exe:
        raise GeneratorError(
            "ISLa is not installed.\n  Fix: spreadex generators install isla"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    # Grammar and constraint files are POSITIONAL. The -g/-c flags take the
    # grammar and constraint *source text*, so passing a path there makes ISLa
    # try to parse the path itself as a grammar.
    # -n alone is not enough: -f (free instantiations, default 10) caps how
    # many concrete inputs each solution is expanded into, so `-n 150` on an
    # unconstrained grammar still yields 10. Both have to be raised.
    cmd = [exe, "solve", "-n", str(n), "-f", str(max(n, 10)), "-d", str(out_dir), str(grammar)]
    constraint = _sibling_constraint(grammar)
    if constraint:
        cmd.append(str(constraint))
    _run(cmd, timeout, "ISLa")
    return _collect(out_dir)


def _sibling_constraint(grammar: Path) -> Path | None:
    """ISLa constraints live in a separate .isla file beside the grammar."""
    candidate = grammar.with_suffix(".isla")
    return candidate if candidate.exists() else None


# --------------------------------------------------------------- grammarinator

_GRAMMAR_HEADER = re.compile(r"^\s*(?:lexer\s+|parser\s+)?grammar\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.M)


def generate_grammarinator(mgr, grammar: Path, n: int, out_dir: Path, seed: int, timeout: float):
    """Grammarinator is two steps: compile the grammar, then generate from it.

    `grammarinator-process` turns a .g4 into a Python generator class, which is
    slow and depends only on the grammar, so it is cached by grammar content.
    """
    process = mgr.executable_for("grammarinator", "grammarinator-process")
    generate_exe = mgr.executable_for("grammarinator", "grammarinator-generate")
    if not process or not generate_exe:
        raise GeneratorError(
            "Grammarinator is not installed.\n"
            "  Fix: spreadex generators install grammarinator"
        )

    text = grammar.read_text()
    m = _GRAMMAR_HEADER.search(text)
    if not m:
        raise GeneratorError(
            f"{grammar.name} has no `grammar <Name>;` header, so Grammarinator "
            f"cannot name the generator class it builds."
        )
    grammar_name = m.group(1)

    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    compiled = mgr.cache_dir / "grammarinator" / digest
    module = compiled / f"{grammar_name}Generator.py"
    if not module.exists():
        compiled.mkdir(parents=True, exist_ok=True)
        _run([process, "-o", str(compiled), str(grammar)], timeout, "grammarinator-process")
        if not module.exists():
            produced = ", ".join(p.name for p in compiled.glob("*.py")) or "nothing"
            raise GeneratorError(
                f"grammarinator-process did not produce {module.name} (produced: {produced})."
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    start_rule = _start_rule(text)
    _run([
        generate_exe, f"{grammar_name}Generator.{grammar_name}Generator",
        "-r", start_rule,
        "-o", str(out_dir / "gi_%d.txt"),
        "-n", str(n),
        "-d", "30",
        # Seeded like every other generator, so a campaign is reproducible.
        "--random-seed", str(seed),
        # One worker: parallel workers interleave their random streams, which a seed cannot fix.
        "-j", "1",
        "--sys-path", str(compiled),
    ], timeout, "grammarinator-generate")
    return _collect(out_dir)


def _start_rule(text: str) -> str:
    """Grammarinator needs a start rule by name; take the first parser rule."""
    for m in re.finditer(r"^\s*([a-z][A-Za-z0-9_]*)\s*:", text, re.M):
        return m.group(1)
    raise GeneratorError(
        "No parser rule found to start generation from "
        "(Grammarinator needs a lowercase rule name)."
    )


ADAPTERS = {
    "fuzzingbook": generate_fuzzingbook,
    "fandango": generate_fandango,
    "isla": generate_isla,
    "grammarinator": generate_grammarinator,
}


def generate(
    generator_id: str,
    grammar: Path,
    count: int,
    seed: int = 42,
    timeout: float = 300.0,
    manager: GeneratorManager | None = None,
) -> GeneratedBatch:
    """Run one generator and return what it produced, with its cost."""
    mgr = manager or GeneratorManager()
    try:
        adapter = ADAPTERS[generator_id]
    except KeyError:
        raise GeneratorError(
            f"No adapter for generator {generator_id!r}. "
            f"Available: {', '.join(sorted(ADAPTERS))}"
        ) from None

    grammar = Path(grammar)
    if not grammar.exists():
        raise GeneratorError(
            f"Grammar not found for {generator_id}: {grammar}\n"
            f"  Fix: correct the path under `grammar:` in spreadex.yaml."
        )

    started = time.perf_counter()
    partial = False
    with tempfile.TemporaryDirectory(prefix=f"spreadex-{generator_id}-") as tmp:
        out_dir = Path(tmp)
        try:
            inputs = adapter(mgr, grammar, count, out_dir, seed, timeout)
        except GeneratorError:
            # A generator that ran out of budget has usually written something
            # already. Keeping it is strictly better than discarding the work
            # and reporting nothing -- rich grammars routinely exhaust
            # FuzzingBook's and ISLa's budget while still yielding inputs.
            inputs = _collect(out_dir)
            if not inputs:
                raise
            partial = True
    elapsed_ms = (time.perf_counter() - started) * 1000
    return GeneratedBatch(generator=generator_id, inputs=inputs,
                          elapsed_ms=elapsed_ms, partial=partial)
