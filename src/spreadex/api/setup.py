"""The setup wizard's backend: inspect, configure, install and launch.

Everything here is driven by what the user typed and reviewed. The server
never invents a command to run -- it writes the configuration the user
confirmed, and later executes exactly that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..core.config import CONFIG_NAME, ConfigError, load_config
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
            "installed": status.installed,
            "version": status.version,
            "where": status.where,
            "emittable": gen.id in RENDERERS,
            "selected": gen.id in (config.generators or []),
        })
    return {"generators": out}


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


def save_grammar(config, body: dict) -> dict[str, Any]:
    """Write an accepted proposal into the project.

    Refuses to leave the project directory, and refuses to write a grammar the
    validator rejects -- accepting a proposal has to mean it passed.
    """
    from ..grammar import GrammarError, diagnose, parse_bnf

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
            report = diagnose(parse_bnf(text))
        except GrammarError as exc:
            return {"ok": False, "error": f"refusing to save: {exc}"}
        if report.errors:
            return {"ok": False,
                    "error": "refusing to save: " + "; ".join(f.message for f in report.errors)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return {"ok": True, "written": str(target.relative_to(root))}


# ------------------------------------------------------- command verification

#: Long enough for a JVM to start, short enough that a hung command does not
#: hold the wizard. A real campaign uses the project's own timeout.
PROBE_TIMEOUT_S = 20.0

#: Capped so a chatty command cannot fill the browser. The user is checking
#: "did this run at all", not reading a log.
PROBE_PREVIEW = 4000


def probe_target(config, body: dict) -> dict[str, Any]:
    """Run a proposed command once on a sample input and report what happened.

    The user has just typed a command. Finding out at the end of a campaign
    that every one of 500 inputs "crashed" because of a typo is the worst way
    to learn it, so the wizard runs it once, here, and shows the result.

    This is deliberately NOT a verdict. It reports exit code and output and
    leaves the judgement to the person reading it -- a parser rejecting the
    sample with a non-zero exit is working correctly, and saying otherwise
    would teach exactly the wrong lesson before step 4 asks about it.
    """
    import tempfile

    from ..exec.runner import Limits, Target, run_one

    command = body.get("command")
    if isinstance(command, str):
        command = command.split()
    if not isinstance(command, list) or not [c for c in command if str(c).strip()]:
        return {"ok": False, "error": "enter a command first"}
    command = [str(c) for c in command if str(c).strip()]

    sample = body.get("sample")
    if not isinstance(sample, str) or not sample:
        sample = "1 + 1\n"

    target = Target(
        name="probe",
        command=command,
        base_dir=config.project_root,
        limits=Limits(timeout_s=PROBE_TIMEOUT_S),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.txt"
        path.write_text(sample)
        try:
            obs = run_one(target, path)
        except RuntimeError as exc:
            # run_one turns a missing command into a configuration error with
            # its own CLI-shaped advice; in the wizard the fix is on screen.
            if "not found" in str(exc):
                return {"ok": False,
                        "error": f"{command[0]!r} was not found. Check the path, "
                                 f"or install it and try again."}
            return {"ok": False, "error": str(exc)}
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
    }
