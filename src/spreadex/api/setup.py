"""The setup wizard's backend: inspect, configure, install and launch.

Everything here is driven by what the user typed and reviewed. The server
never invents a command to run -- it writes the configuration the user
confirmed, and later executes exactly that.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from ..core.config import CONFIG_NAME, ConfigError, load_config
from ..exec.runner import _parse_duration
from ..generators import GeneratorError, GeneratorManager

GRAMMAR_SUFFIXES = {".bnf", ".g4", ".fan", ".ebnf", ".isla", ".py"}
MAX_SCAN = 4000


# ----------------------------------------------------------------- config

def read_config(config) -> dict[str, Any]:
    path = config.project_root / CONFIG_NAME
    return {
        "path": str(path),
        "exists": path.is_file(),
        "raw": path.read_text() if path.is_file() else "",
        "parsed": config.raw,
        "project_root": str(config.project_root),
    }


def save_config(config, body: dict) -> dict[str, Any]:
    """Validate a proposed spreadex.yaml, and write it only when asked.

    A dry run is the default so the wizard can show what would change before
    anything touches the project.
    """
    raw = body.get("yaml")
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": False, "errors": ["the configuration is empty"]}

    path = config.project_root / CONFIG_NAME
    errors: list[str] = []
    try:
        parsed = yaml.safe_load(raw)
        if not isinstance(parsed, dict):
            errors.append("the configuration must be a mapping")
    except yaml.YAMLError as exc:
        errors.append(f"not valid YAML: {exc}")
        parsed = None

    # Validate by loading it exactly as the CLI would, from a scratch copy, so
    # a broken configuration can never be written over a working one.
    if not errors:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / CONFIG_NAME
            probe.write_text(raw)
            try:
                load_config(probe)
            except ConfigError as exc:
                errors.append(str(exc))

    if errors:
        return {"ok": False, "errors": errors}
    if not body.get("write"):
        return {"ok": True, "errors": [], "preview": raw, "would_write": str(path)}

    path.write_text(raw)
    return {"ok": True, "errors": [], "written": str(path)}


# ------------------------------------------------------------- inspection

def list_candidate_grammars(config) -> dict[str, Any]:
    """Grammar-shaped files in the project, so the wizard can offer a choice."""
    root = config.project_root
    found: list[dict[str, Any]] = []
    seen = 0
    for path in sorted(root.rglob("*")):
        seen += 1
        if seen > MAX_SCAN:
            break
        if not path.is_file() or path.suffix.lower() not in GRAMMAR_SUFFIXES:
            continue
        if any(part in {".spreadex", ".git", "__pycache__", ".venv"} for part in path.parts):
            continue
        if path.suffix.lower() == ".py":
            # Only Python files that actually hold a grammar dict.
            head = path.read_text(errors="replace")[:4000]
            if "GRAMMAR" not in head and "_grammar" not in head:
                continue
        found.append({
            "path": str(path.relative_to(root)),
            "suffix": path.suffix.lower(),
            "size": path.stat().st_size,
        })
    return {"grammars": found, "truncated": seen > MAX_SCAN}


GENERATOR_FAMILIES = [
    {"id": "probabilistic", "label": "Probabilistic"},
    {"id": "constraint-based", "label": "Constraint-based"},
    {"id": "coverage-guided", "label": "Coverage-guided"},
    {"id": "llm-based", "label": "LLM-based"},
]

UPCOMING_GENERATORS = [
    {"id": "clusgram", "name": "ClusGram", "family": "coverage-guided", "ours": True,
     "summary": "Rule-coverage-driven generation for diverse inputs."},
    {"id": "nautilus", "name": "Nautilus", "family": "coverage-guided",
     "summary": "Coverage-guided grammar fuzzer with feedback."},
    {"id": "dharma", "name": "Dharma", "family": "probabilistic",
     "summary": "Mozilla's generational grammar fuzzer."},
    {"id": "fuzz4all", "name": "Fuzz4All", "family": "llm-based",
     "summary": "LLM-driven universal fuzzer (Xia et al., ICSE 2024). Planned; no model is bundled."},
]


def generator_status(config) -> dict[str, Any]:
    from ..grammar import RENDERERS

    mgr = GeneratorManager()
    out = []
    for status in mgr.status_all():
        gen = status.generator
        out.append({
            "id": gen.id,
            "name": gen.name,
            "summary": gen.summary,
            "homepage": gen.homepage,
            "license": gen.license,
            "notes": gen.notes,
            "dialect": gen.grammar_dialect,
            "constraints": gen.supports_constraints,
            "family": gen.family,
            "installed": status.installed,
            "version": status.version,
            "where": status.where,
            "emittable": gen.id in RENDERERS,
            "selected": gen.id in (config.generators or []),
        })
    # Named in the research tool or planned, but not generators SpreadEx can run. Shown inactive
    # so nobody wonders where they are; never selectable, never written to the config.
    return {"generators": out, "upcoming": UPCOMING_GENERATORS, "families": GENERATOR_FAMILIES,
            "options": {"constraint_capable": [g["id"] for g in out if g["constraints"]]}}


# ---------------------------------------------------------------- actions

def start_install(server, body: dict) -> dict[str, Any]:
    gid = body.get("id")
    mgr = GeneratorManager()
    try:
        gen = mgr.get(gid)
    except GeneratorError as exc:
        return {"ok": False, "error": str(exc)}

    def work(job):
        job.log(f"Installing {gen.name} into its own environment...")
        status = mgr.install(gen.id, log=job.log)
        return {"id": gen.id, "version": status.version, "where": status.where}

    try:
        server.spreadex_jobs.start("install", f"install {gen.name}", work)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "started": gen.id}


def start_run(server, body: dict) -> dict[str, Any]:
    """Launch a campaign using the configuration already on disk.

    The configuration is re-read from the project rather than taken from the
    request, so what runs is exactly what the user reviewed and saved.
    """
    from ..core.campaign import Campaign
    from ..core.config import find_config

    path = find_config(server.spreadex_config.project_root)
    if path is None:
        return {"ok": False, "error": f"no {CONFIG_NAME} in this project yet"}
    try:
        config = load_config(path)
    except ConfigError as exc:
        return {"ok": False, "error": str(exc)}

    jobs = int(body.get("jobs") or 1)
    budget = body.get("budget")
    if budget:
        from ..exec.runner import _parse_duration

        try:
            config.budget.execution_s = _parse_duration(budget)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad budget {budget!r}"}

    command = " ".join(config.targets[0].command) if config.targets else "?"

    def work(job):
        job.log(f"Running: {command}")
        result = Campaign(config, log=job.log).run(jobs=jobs)
        return {
            "run_id": result.run_id,
            "executed": result.executed,
            "verdicts": result.verdicts,
            "new_signatures": len(result.new_signatures),
        }

    try:
        server.spreadex_jobs.start("run", "campaign", work)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    # Echo the command back so the UI can show what it just set going.
    return {"ok": True, "command": command}


# -------------------------------------------------------- assistance (opt-in)

def llm_providers() -> dict[str, Any]:
    from ..llm import available

    return {"providers": available()}


def _llm_kwargs(body: dict) -> dict[str, Any]:
    """Pull the model settings out of a request.

    A key supplied here lives for the duration of this call only. It is never
    written to disk, never logged, and never echoed back.
    """
    return {
        "provider": body.get("provider") or "openai",
        "model": (body.get("model") or "").strip() or None,
        "api_key": (body.get("api_key") or "").strip() or None,
        "base_url": (body.get("base_url") or "").strip() or None,
    }


def assist(config, body: dict) -> dict[str, Any]:
    """Ask a model to propose a grammar or constraints, then validate it."""
    from ..llm import LLMError, constraints_for, infer_grammar, read_examples, repair_grammar

    task = body.get("task")
    generators = config.generators or ["fuzzingbook", "isla", "fandango", "grammarinator"]
    try:
        if task == "infer":
            examples = []
            corpus = (body.get("corpus") or "").strip()
            if corpus:
                path = (config.project_root / corpus).resolve()
                if not path.is_dir() or config.project_root.resolve() not in path.parents:
                    return {"ok": False, "error": "that corpus is not inside this project"}
                examples = read_examples(path)
            examples += [e for e in (body.get("examples") or []) if e.strip()]
            proposal = infer_grammar(examples, body.get("description", ""),
                                     generators=generators, **_llm_kwargs(body))
        elif task == "repair":
            proposal = repair_grammar(body.get("grammar", ""), generators=generators,
                                      **_llm_kwargs(body))
        elif task == "constraints":
            proposal = constraints_for(body.get("generator", "fandango"),
                                       body.get("constraints", ""),
                                       body.get("grammar", ""), **_llm_kwargs(body))
        else:
            return {"ok": False, "error": f"unknown task {task!r}"}
    except LLMError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "proposal": proposal.as_dict()}


def _parse_for(rel: str, text: str):
    """Parse grammar text with the front end its file extension names."""
    from ..grammar.parse import parse_bnf, parse_fuzzingbook

    suffix = Path(rel).suffix.lower()
    if suffix == ".g4":
        from ..grammar.antlr import parse_antlr
        return parse_antlr(text, source_path=rel)[0]
    if suffix == ".py":
        return parse_fuzzingbook(text, source_path=rel)
    fmt = {".fan": "fandango", ".isla": "isla", ".ebnf": "ebnf"}.get(suffix, "bnf")
    return parse_bnf(text, source_format=fmt, source_path=rel)


#: Grammars that ship inside the wheel. Deliberately a short, honest list: each
#: entry is a file SpreadEx's own tests exercise, not a registry of languages.
BUNDLED_GRAMMARS = [
    {"id": "arithmetic", "name": "Arithmetic expressions", "language": "Calculator",
     "file": "calc.bnf",
     "summary": "Numbers, + - * / %, brackets. The grammar behind `spreadex demo`."},
]


def bundled_grammars() -> dict[str, Any]:
    from ..grammar import GrammarError, diagnose
    from importlib.resources import files

    out = []
    for g in BUNDLED_GRAMMARS:
        text = (files("spreadex.demo") / "project" / g["file"]).read_text()
        try:
            grammar = _parse_for(g["file"], text)
            rules, start = len(grammar.rules), grammar.start
            ok = not diagnose(grammar).errors
        except GrammarError:
            rules, start, ok = 0, "", False
        out.append({**{k: v for k, v in g.items() if k != "file"}, "text": text,
                    "rules": rules, "start": start, "ok": ok, "path": f"grammars/{g['id']}.bnf"})
    return {"grammars": out}


def save_grammar(config, body: dict) -> dict[str, Any]:
    """Write an accepted proposal into the project.

    Refuses to leave the project directory, and refuses to write a grammar the
    validator rejects -- accepting a proposal has to mean it passed.
    """
    from ..grammar import GrammarError, diagnose

    rel = (body.get("path") or "").strip()
    text = body.get("text") or ""
    if not rel or not text.strip():
        return {"ok": False, "error": "need a path and some grammar text"}

    target = (config.project_root / rel).resolve()
    root = config.project_root.resolve()
    if root != target.parent and root not in target.parents:
        return {"ok": False, "error": "the grammar must be written inside this project"}

    if not body.get("allow_invalid"):
        try:
            report = diagnose(_parse_for(rel, text))
        except GrammarError as exc:
            return {"ok": False, "error": f"refusing to save: {exc}"}
        if report.errors:
            return {"ok": False,
                    "error": "refusing to save: " + "; ".join(f.message for f in report.errors)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return {"ok": True, "written": str(target.relative_to(root))}


# ------------------------------------------------------ semantic guidance (step 2)

def _spec_target(config, rel: str):
    """Resolve a path under the project and refuse anything that leaves it."""
    root = config.project_root.resolve()
    target = (root / rel).resolve()
    if root not in target.parents:
        return None
    return target


def read_spec(config) -> dict[str, Any]:
    """What is configured, with enough text to show, and what this install can read."""
    from ..spec import docs_support

    sem = config.semantics
    texts = {}
    for rel in sem.guidance:
        try:
            texts[rel] = (config.project_root / rel).read_text(errors="replace")[:20000]
        except OSError:
            texts[rel] = ""
    return {"semantics": sem.as_dict(), "texts": texts, "docs": docs_support(),
            "formats": [".txt", ".md", ".pdf", ".docx"]}


def extract_document(config, body: dict) -> dict[str, Any]:
    """Read an uploaded document into text for the user to review. Writes nothing."""
    import base64
    import binascii

    from ..spec import SpecError, extract_text

    name = str(body.get("name") or "")
    try:
        data = base64.b64decode(body.get("data") or "", validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "that upload could not be decoded"}
    try:
        return {"ok": True, **extract_text(name, data).as_dict()}
    except SpecError as exc:
        return {"ok": False, "error": str(exc)}


def save_spec(config, body: dict) -> dict[str, Any]:
    """Write reviewed text (and optionally the original document) under spec/.

    kind = guidance | structured | native:<generator>. The server never edits
    spreadex.yaml here; the wizard records the path when the user saves the config.
    """
    import base64
    import binascii

    from ..spec import GUIDANCE_SUFFIXES, NATIVE_GENERATORS, SPEC_DIR, safe_spec_name
    from ..spec.model import MAX_SPEC_BYTES

    kind = str(body.get("kind") or "guidance")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "there is nothing to save yet; write or upload something first"}
    if len(text.encode()) > MAX_SPEC_BYTES:
        return {"ok": False, "error": f"that is over {MAX_SPEC_BYTES // 1000} KB; keep rules short and focused"}

    if kind == "guidance":
        name = safe_spec_name(body.get("name") or "", "semantics.md")
        if not name.lower().endswith(GUIDANCE_SUFFIXES):
            name += ".md"
    elif kind == "structured":
        name = safe_spec_name(body.get("name") or "", "constraints.yaml")
        if not name.lower().endswith((".yaml", ".yml", ".json")):
            name += ".yaml"
        import yaml
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return {"ok": False, "error": f"that is not valid YAML/JSON: {exc}"}
    elif kind.startswith("native:") and kind.split(":", 1)[1] in NATIVE_GENERATORS:
        gid = kind.split(":", 1)[1]
        name = safe_spec_name(body.get("name") or "", f"constraints.{'fan' if gid == 'fandango' else 'isla'}")
    else:
        return {"ok": False, "error": f"unknown kind {kind!r}"}

    rel = f"{SPEC_DIR}/{name}"
    target = _spec_target(config, rel)
    if target is None:
        return {"ok": False, "error": "the specification must be written inside this project"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)

    original = body.get("original")
    if isinstance(original, dict) and original.get("data"):
        try:
            blob = base64.b64decode(original["data"], validate=True)
        except (binascii.Error, ValueError):
            blob = b""
        oname = safe_spec_name(original.get("name") or "", "")
        if blob and oname and len(blob) <= 5_000_000 and oname != name:
            (target.parent / oname).write_bytes(blob)
    return {"ok": True, "written": rel}


# ------------------------------------------------------- command verification

#: A ceiling on what the connection test may ask for, whatever the config says.
#: The campaign's own timeout is used (that is what it will experience), but a
#: wizard request should not be able to hold a server thread for ten minutes.
PROBE_MAX_TIMEOUT_S = 60.0

#: Capped so a chatty command cannot fill the browser. The user is checking
#: "did this run at all", not reading a log.
PROBE_PREVIEW = 4000

_VERSION_LINE = re.compile(r"\d+\.\d+")


def _runtime_label(target) -> str | None:
    """The interpreter's own version, for "Runtime: Java 21".

    Only when the command starts with a BARE name (java, python3, node -- found
    on PATH): those are runtimes. A path such as ./parser is the user's own
    program, not a runtime, and `--version` on someone's program is at best
    meaningless (the demo SUT answers it with "cannot read input") and at worst
    an unwanted extra run.

    Even then the answer is only believed if the call succeeded and the first
    line contains something that looks like a version. Otherwise nothing is
    shown: no label is better than a stack-trace fragment in a "Runtime" box.
    """
    exe = target.command[0]
    if os.sep in exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, timeout=5, check=False,
            stdin=subprocess.DEVNULL, cwd=target.resolved_cwd() or None,
            env={**os.environ, **target.env},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip().splitlines()
    first = text[0].strip() if text else ""
    return first[:60] if first and _VERSION_LINE.search(first) else None


def _clean_probe_options(body: dict) -> tuple[dict | None, str | None]:
    """Validate the request into a target spec, or say what is wrong with it."""
    command = body.get("command")
    if isinstance(command, str):
        command = command.split()
    if not isinstance(command, list) or not [c for c in command if str(c).strip()]:
        return None, "enter a command first"
    spec: dict[str, Any] = {"name": "probe", "command": [str(c) for c in command if str(c).strip()]}

    mode = body.get("input_mode") or "file"
    if mode not in ("file", "stdin"):
        return None, f"input_mode must be 'file' or 'stdin', not {mode!r}"
    spec["input_mode"] = mode

    cwd = body.get("cwd")
    if cwd not in (None, ""):
        if not isinstance(cwd, str):
            return None, "the working directory must be a path"
        spec["cwd"] = cwd

    env = body.get("env")
    if env not in (None, {}):
        if not isinstance(env, dict) or not all(isinstance(k, str) and k for k in env):
            return None, "environment variables must be NAME=value pairs"
        if len(env) > 64:
            return None, "too many environment variables (the limit is 64)"
        spec["env"] = {k: str(v) for k, v in env.items()}

    try:
        timeout = _parse_duration(body.get("timeout") or "5s")
    except ValueError:
        return None, f"{body.get('timeout')!r} is not a duration; use 5, 5s, 2m or 1h"
    if timeout <= 0:
        return None, "the timeout must be more than zero"
    spec["timeout"] = min(timeout, PROBE_MAX_TIMEOUT_S)

    mem = body.get("memory_mb")
    if mem not in (None, ""):
        if isinstance(mem, bool) or not isinstance(mem, int) or mem <= 0:
            return None, "the memory limit must be a positive whole number of megabytes"
        spec["memory_mb"] = mem
    return spec, None


def probe_target(config, body: dict) -> dict[str, Any]:
    """Run a proposed command once on a sample input and report what happened.

    The user has just typed a command. Finding out at the end of a campaign
    that every one of 500 inputs "crashed" because of a typo is the worst way
    to learn it, so the wizard runs it once, here, and shows the result.

    The target is built by Target.from_config -- the code a campaign uses -- from
    the same options (working directory, environment, stdin, timeout, memory),
    so a passing test means the campaign will run it the same way.

    This is deliberately NOT a verdict. It reports exit code and output and
    leaves the judgement to the person reading it -- a parser rejecting the
    sample with a non-zero exit is working correctly, and saying otherwise
    would teach exactly the wrong lesson before step 4 asks about it.
    """
    import tempfile

    from ..exec.runner import Target, run_one

    spec, problem = _clean_probe_options(body)
    if problem:
        return {"ok": False, "error": problem}
    command = spec["command"]

    sample = body.get("sample")
    if not isinstance(sample, str) or not sample:
        sample = "1 + 1\n"

    target = Target.from_config(spec, base_dir=config.project_root)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.txt"
        path.write_text(sample)
        try:
            obs = run_one(target, path)
        except RuntimeError as exc:
            # run_one turns a missing command into a configuration error with
            # its own CLI-shaped advice; in the wizard the fix is on screen.
            text = str(exc)
            if "working directory not found" in text:
                return {"ok": False, "error": text.split("\n")[0].split(": ", 1)[1]
                        if ": " in text else text}
            if "not found" in text:
                return {"ok": False,
                        "error": f"{command[0]!r} was not found. Check the path, "
                                 f"or install it and try again."}
            return {"ok": False, "error": text}
        except PermissionError:
            return {"ok": False, "error": f"{command[0]!r} is not executable. "
                                          f"`chmod +x` it and try again."}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        rendered = target.render(path)

    return {
        "ok": True,
        "ran": True,
        "command": rendered,
        "exit_code": obs.exit_code,
        "signal": obs.signal,
        "timed_out": obs.timed_out,
        "duration_ms": round(obs.duration_ms, 1),
        "stdout": (obs.stdout_preview or "")[:PROBE_PREVIEW],
        "stderr": (obs.stderr_preview or "")[:PROBE_PREVIEW],
        "sample": sample,
        "substituted": any("{input}" in part for part in command),
        "input_mode": target.input_mode,
        "timeout_s": target.limits.timeout_s,
        "runtime": _runtime_label(target),
    }
