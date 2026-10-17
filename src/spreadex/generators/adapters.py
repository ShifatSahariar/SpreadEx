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
from dataclasses import dataclass, field
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
    #: Generator-specific accounting (e.g. Fuzz4All's SUT executions and LLM usage), for the manifest.
    details: dict = field(default_factory=dict)

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


def _run(cmd: list[str], timeout: float, what: str,
         env: dict | None = None) -> subprocess.CompletedProcess:
    # Every generator runs in Python. A fixed hash seed is what makes a seeded generator actually
    # reproducible: without it, set and dict iteration order changes from process to process
    # (Fandango 1.3 gave different inputs for the same --random-seed until this was pinned).
    # A caller that passes `env` (an LLM generator) passes a complete, allow-listed environment.
    env = {**(env if env is not None else os.environ), "PYTHONHASHSEED": "0"}
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
        from ..llm.redact import redact
        err = redact((proc.stderr or b"").decode(errors="replace").strip()[-2000:])
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
    args = ["solve", "-n", str(n), "-f", str(max(n, 10)), "-d", str(out_dir), str(grammar)]
    constraint = _sibling_constraint(grammar)
    if constraint:
        args.append(str(constraint))
    # `isla solve` has no seed option, and its free instantiations draw from Python's `random`,
    # so two runs of the same configuration produced different inputs (2 of 150 shared on the
    # Rhino example). Seeding `random` before handing over to ISLa's own CLI entry point makes
    # the same seed give the same inputs, as for the other generators.
    _run([mgr.python_for("isla"), "-c", _ISLA_SEEDED, str(seed), *args], timeout, "ISLa")
    return _collect(out_dir)


_ISLA_SEEDED = (
    "import random, sys\n"
    "random.seed(int(sys.argv[1]))\n"
    "sys.argv = ['isla'] + sys.argv[2:]\n"
    "from isla.cli import main\n"
    "main()\n"
)


def _sibling_constraint(grammar: Path) -> Path | None:
    """ISLa constraints live in a separate .isla file beside the grammar."""
    candidate = grammar.with_suffix(".isla")
    return candidate if candidate.exists() else None



# ------------------------------------------------------------------- fuzz4all

# Runs inside the Fuzz4All environment. Reads one JSON job (no credentials: the endpoint and key
# arrive in the process environment), then follows the ClusGram study's sequence for the pinned
# artifact: an autoprompting setup phase on its own Target (the paper's probe count), then
# upstream's own `fuzz()` loop with on-the-fly validation on a second Target that reuses the
# selected prompt. Nothing of the algorithm is reimplemented here.
_FUZZ4ALL_DRIVER = r"""
import json, math, os, sys, time
job = json.load(open(sys.argv[1]))
sys.path.insert(0, job["artifact"])
import random
random.seed(job["seed"])
from Fuzz4All import fuzz as f4a_fuzz
from Fuzz4All.make_target import make_target_with_config
from Fuzz4All.target.spreadex.spreadex_target import SpreadExTarget
import Fuzz4All.util.api_request as api_request

staging = job["staging"]
os.makedirs(staging, exist_ok=True)
style = job["comment_style"]
def comment(text):
    if style == "c": return "/* " + text + " */"
    prefix = {"hash": "#", "dashdash": "--", "rem": "REM"}[style]
    return "\n".join(prefix + " " + line for line in text.splitlines())
trigger = comment("Please create a very short program which uses " + job["language_name"]
                  + " features in a complex way")

def config(batch_size):
    return {
        "fuzzing": {"output_folder": staging, "num": job["num"], "total_time": job["hours"],
                    "log_level": 3, "otf": True, "resume": False, "evaluate": False,
                    "use_hand_written_prompt": False, "no_input_prompt": False,
                    "prompt_strategy": 2, "target_name": "spreadex"},
        "target": {"language": "spreadex", "path_documentation": job["documentation"],
                   "path_example_code": job["example"], "trigger_to_generate_input": trigger,
                   "input_hint": "", "path_hand_written_prompt": None, "target_string": ""},
        "llm": {"temperature": job["temperature"], "batch_size": batch_size, "device": "api",
                "model_name": "openai/" + job["model"], "distillation_model": "openai/" + job["model"],
                "max_length": job["max_length"]},
        "spreadex": {"spreadex_path": job["spreadex_path"], "targets": job["targets"],
                     "scratch_dir": job["scratch_dir"],
                     "oracle": job["oracle"], "comment_style": style,
                     "language_name": job["language_name"], "input_extension": job["extension"]},
    }

calls = {"setup": 0, "generation": 0}
def counted(target, phase):
    original = target.generate_model
    def wrapper():
        calls[phase] += 1
        return original()
    target.generate_model = wrapper
    return target

t0 = time.time()
setup = make_target_with_config(config(job["probe_batch"]))
setup.initialize()                     # runs auto_prompt: distillation + scored candidates
setup_usage = dict(getattr(setup.model, "usage", {}) or {})
distill_usage = dict(getattr(api_request, "USAGE", {}) or {})
setup_s = time.time() - t0

gen = counted(make_target_with_config(config(job["batch_size"])), "generation")
f4a_fuzz.fuzz(target=gen, number_of_iterations=job["num"], total_time=job["hours"],
              output_folder=staging, resume=False, otf=True)
gen_usage = dict(getattr(gen.model, "usage", {}) or {})

prompts = os.path.join(staging, "prompts")
def read(name):
    p = os.path.join(prompts, name)
    return open(p, encoding="utf-8").read() if os.path.isfile(p) else None
print(json.dumps({"setup_seconds": round(setup_s, 2),
                  "usage": {"distillation": distill_usage, "prompt_scoring": setup_usage,
                            "generation": gen_usage},
                  "generation_batches": calls["generation"],
                  "best_prompt": read("best_prompt.txt"),
                  "candidate_scores": read("scores.txt")}))
"""

#: Fuzz4All settings, as in the ClusGram study (configs/generation_settings/fuzz4all.py).
FUZZ4ALL_DEFAULTS = {"temperature": 1.0, "batch_size": 25, "probe_batch": 30, "max_length": 1024}
#: How each comment style is chosen when the user does not say, from the input extension.
COMMENT_STYLE_BY_EXTENSION = {".js": "c", ".c": "c", ".cpp": "c", ".java": "c", ".go": "c",
                              ".ts": "c", ".py": "hash", ".rb": "hash", ".sh": "hash",
                              ".lua": "dashdash", ".sql": "dashdash", ".bas": "rem"}


def _batch_size_for(n: int, preferred: int) -> int:
    """Largest batch <= preferred that divides n: upstream generates whole batches, and the
    corpus must be every candidate it wrote, in order."""
    for b in range(min(preferred, max(1, n)), 0, -1):
        if n % b == 0:
            return b
    return 1


def _staged(staging: Path) -> list[Path]:
    return sorted(staging.glob("*.fuzz"), key=lambda p: int(p.stem) if p.stem.isdigit() else 1 << 30)


def _check_reachable(base_url: str, timeout: float = 5.0) -> None:
    """A TCP connection to the endpoint, before anything is spent. Upstream retries connection
    errors forever, so an unreachable endpoint would otherwise burn the whole generation budget
    and be reported as a budget problem. No request is sent and no tokens are used."""
    import socket
    from urllib.parse import urlparse

    u = urlparse(base_url)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        socket.create_connection((u.hostname, port), timeout=timeout).close()
    except OSError as exc:
        raise GeneratorError(
            f"Fuzz4All failed: the LLM endpoint {u.hostname}:{port} cannot be reached ({exc}).\n"
            f"  Fix: check the base URL and your network, or start the local model server.") from None


def generate_fuzz4all(mgr, grammar, n: int, out_dir: Path, seed: int, timeout: float,
                      context: dict | None = None):
    """Run the pinned Fuzz4All artifact for `n` candidates, with SpreadEx's target and oracle."""
    from ..llm.settings import LLMSettingsError, resolve, subprocess_env

    if not context:
        raise GeneratorError("Fuzz4All needs the campaign's context (documentation, SUT, LLM settings).")
    status = mgr.status("fuzz4all")
    if not status.installed:
        raise GeneratorError(f"Fuzz4All is not ready ({status.detail}).\\n"
                             f"  Fix: spreadex generators install fuzz4all")
    try:
        llm = resolve(context.get("llm"))
    except LLMSettingsError as exc:
        raise GeneratorError(str(exc)) from None

    _check_reachable(llm.base_url)
    options = {**FUZZ4ALL_DEFAULTS, **(context.get("options") or {})}
    # Outside out_dir, which is scanned for inputs, and removed afterwards.
    work = Path(tempfile.mkdtemp(prefix="spreadex-fuzz4all-"))
    staging = work / "staging"
    docs = context.get("documentation") or []
    if not docs:
        raise GeneratorError(
            "Fuzz4All writes programs from documentation, and this project has none.\\n"
            "  Fix: add a short description of the input language under `semantics.guidance` "
            "(Workbench step 2).")
    documentation = work / "documentation.md"
    documentation.write_text("\\n\\n".join(Path(d).read_text(encoding="utf-8", errors="replace") for d in docs))
    example = None
    if context.get("example"):
        example = work / "example.txt"
        example.write_bytes(Path(context["example"]).read_bytes())
    extension = context.get("extension") or ""
    style = context.get("comment_style") or COMMENT_STYLE_BY_EXTENSION.get(extension, "c")

    import spreadex
    job = {
        "artifact": str(mgr.source_dir("fuzz4all")), "seed": seed, "staging": str(staging),
        "num": n, "hours": max(timeout, 1.0) / 3600.0, "model": llm.model,
        "temperature": float(options["temperature"]), "max_length": int(options["max_length"]),
        "batch_size": _batch_size_for(n, int(options["batch_size"])),
        "probe_batch": int(options["probe_batch"]),
        "documentation": str(documentation), "example": str(example) if example else None,
        "comment_style": style, "language_name": context.get("language_name") or "program",
        "extension": extension, "targets": context["targets"], "oracle": context.get("oracle") or {},
        "spreadex_path": str(Path(spreadex.__file__).resolve().parents[1]),
        "scratch_dir": str(work / "scratch"),
    }
    job_file = work / "job.json"
    job_file.write_text(json.dumps(job))
    driver = work / "driver.py"
    driver.write_text(_FUZZ4ALL_DRIVER)
    env = subprocess_env(llm)
    out_dir.mkdir(parents=True, exist_ok=True)

    def harvest() -> dict:
        written = 0
        for i, path in enumerate(_staged(staging)):
            data = path.read_bytes()
            (out_dir / f"f4a_{i:05d}.txt").write_bytes(data)
            written += 1
        records = work / "staging" / "validation_records.jsonl"
        executions: dict = {"probe": {}, "corpus": {}}
        if records.is_file():
            for line in records.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                bucket = executions.setdefault(row.get("phase", "corpus"), {})
                bucket[row.get("verdict", "?")] = bucket.get(row.get("verdict", "?"), 0) + 1
        return {"candidates_written": written,
                "sut_executions": {"prompt_scoring": executions.get("probe", {}),
                                   "validation": executions.get("corpus", {}),
                                   "total": sum(sum(b.values()) for b in executions.values())}}

    details = {"artifact": {"commit": mgr.get("fuzz4all").install["commit"],
                            "patch_sha256": mgr.get("fuzz4all").install.get("patch_sha256")},
               "llm": llm.public(), "settings": {k: job[k] for k in
                   ("temperature", "max_length", "batch_size", "probe_batch", "comment_style",
                    "language_name")},
               "inputs": {"documentation_files": [Path(d).name for d in docs],
                          "example": bool(example)}}
    from ..llm.redact import redact_obj
    try:
        try:
            proc = _run([mgr.python_for("fuzz4all"), str(driver), str(job_file)], timeout,
                        "Fuzz4All", env=env)
            try:
                details.update(json.loads(proc.stdout.decode(errors="replace").strip().splitlines()[-1]))
            except (ValueError, IndexError):
                details["driver_output"] = "unreadable"
        except GeneratorError:
            details.update(harvest())
            details["stopped_early"] = True
            (out_dir / "_details.json").write_text(json.dumps(redact_obj(details)))
            raise
        details.update(harvest())
        (out_dir / "_details.json").write_text(json.dumps(redact_obj(details)))
        return [p.read_bytes() for p in sorted(out_dir.glob("f4a_*.txt"))
                if 0 < p.stat().st_size <= MAX_INPUT_BYTES]
    finally:
        shutil.rmtree(work, ignore_errors=True)

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
    "fuzz4all": generate_fuzz4all,
}
#: Generators that take the campaign's context instead of a grammar.
CONTEXT_ADAPTERS = {"fuzz4all"}


def generate(
    generator_id: str,
    grammar: Path,
    count: int,
    seed: int = 42,
    timeout: float = 300.0,
    manager: GeneratorManager | None = None,
    context: dict | None = None,
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

    takes_context = generator_id in CONTEXT_ADAPTERS
    grammar = Path(grammar) if grammar is not None else None
    if not takes_context and (grammar is None or not grammar.exists()):
        raise GeneratorError(
            f"Grammar not found for {generator_id}: {grammar}\n"
            f"  Fix: correct the path under `grammar:` in spreadex.yaml."
        )

    started = time.perf_counter()
    partial = False
    with tempfile.TemporaryDirectory(prefix=f"spreadex-{generator_id}-") as tmp:
        out_dir = Path(tmp)
        try:
            if takes_context:
                inputs = adapter(mgr, grammar, count, out_dir, seed, timeout, context=context)
            else:
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
        details_file = out_dir / "_details.json"
        details = json.loads(details_file.read_text()) if details_file.is_file() else {}
    elapsed_ms = (time.perf_counter() - started) * 1000
    return GeneratedBatch(generator=generator_id, inputs=inputs,
                          elapsed_ms=elapsed_ms, partial=partial, details=details)
