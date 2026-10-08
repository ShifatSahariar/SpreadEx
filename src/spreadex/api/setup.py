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
    # a broken configuration can never be written over a working one. The copy sits in the
    # project folder, hidden and removed straight after, because relative paths in the file
    # (a grammar, a corpus, a constraints file) resolve against the folder it is in.
    if not errors:
        import os
        import tempfile

        fd, tmp = tempfile.mkstemp(prefix=".spreadex-check-", suffix=".yaml", dir=config.project_root)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(raw)
            try:
                load_config(Path(tmp))
            except ConfigError as exc:
                errors.append(str(exc).replace(str(Path(tmp).resolve()), str(path)).replace(tmp, str(path)))
        finally:
            os.unlink(tmp)

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

# `reference` entries were checked against Crossref on 2026-10-06. ClusGram's paper is under review,
# so it shows a dash until there is a venue and year to give.
UPCOMING_GENERATORS = [
    {"id": "clusgram", "name": "ClusGram", "family": "coverage-guided",
     "reference": {"kind": "\u2014"},
     "summary": "Rule-coverage-driven generation for diverse inputs."},
    {"id": "nautilus", "name": "Nautilus", "family": "coverage-guided",
     "reference": {"venue": "NDSS", "year": 2019, "authors": "Aschermann et al.",
                   "title": "NAUTILUS: Fishing for Deep Bugs with Grammars"},
     "summary": "Coverage-guided grammar fuzzer with feedback."},
    {"id": "dharma", "name": "Dharma", "family": "probabilistic",
     # No paper exists (Crossref, 2026-10-06). The repository description is "Generation-based,
     # context-free grammar fuzzer"; it was created in 2015 and is now archived in favour of a fork.
     "reference": {"kind": "Mozilla's grammar fuzzer", "authors": "Mozilla Security",
                   "title": "Dharma: a generation-based, context-free grammar fuzzer",
                   "note": "No paper; open-source repository since 2015"},
     "summary": "Mozilla's generational grammar fuzzer."},
]


def generator_status(config) -> dict[str, Any]:
    from ..grammar import RENDERERS

    from ..core.sources import recorded_sources

    mgr = GeneratorManager()
    try:
        recorded = recorded_sources(config) if config.configured else {}
    except Exception:          # a broken `generation:` entry is reported by doctor and on run
        recorded = {}
    out = []
    for status in mgr.status_all():
        gen = status.generator
        replay_only = gen.install.get("type") == "none"
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
            "reference": gen.reference,
            "installed": status.installed,
            "version": status.version,
            "where": status.where,
            "emittable": gen.id in RENDERERS,
            "selected": gen.id in (config.generators or []),
            # A generator this version can only replay from a recording (e.g. Fuzz4All, whose
            # live generation needs an LLM provider): usable only where a recording is configured.
            "replay_only": replay_only,
            "recorded": gen.id in recorded,
            "unavailable": (gen.install.get("reason") if replay_only and gen.id not in recorded else None),
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


def missing_generators(config) -> list[str]:
    """Selected generators that SpreadEx knows how to install but that are not installed yet.

    The install recipe comes only from the catalog (package name and pinned version), never from
    a model or from anything the request supplies.
    """
    from ..core.sources import recorded_sources

    mgr = GeneratorManager()
    try:
        replayed = recorded_sources(config)
    except GeneratorError:
        replayed = {}
    # A replayed generator needs nothing installed; a replay-only one cannot be installed at all.
    return [gid for gid in (config.generators or [])
            if gid in mgr.catalog and gid not in replayed
            and (getattr(mgr.get(gid), "install", None) or {}).get("type") != "none"
            and not mgr.status(gid).installed]


def start_run(server, body: dict) -> dict[str, Any]:
    """Launch a campaign using the configuration already on disk.

    The configuration is re-read from the project rather than taken from the
    request, so what runs is exactly what the user reviewed and saved.
    """
    from ..core.config import find_config

    path = find_config(server.spreadex_config.project_root)
    if path is None:
        return {"ok": False, "error": f"no {CONFIG_NAME} in this project yet"}
    try:
        config = load_config(path)
    except ConfigError as exc:
        return {"ok": False, "error": str(exc)}
    return _launch(server, config, body)


def _busy(server, config) -> dict | None:
    """Refusal if a campaign is already running here -- from this UI, another UI, or the CLI."""
    from ..core.lock import active_run

    info = active_run(config.state_dir)
    if info is not None or server.spreadex_jobs.busy:
        rid = (info or {}).get("run_id")
        where = "the command line" if (info or {}).get("origin") == "cli" else "the Workbench"
        return {"ok": False, "conflict": True, "active_run": rid,
                "error": f"A campaign is already running ({rid or 'starting'}, started from {where}). "
                         "Open it, or cancel it first."}
    return None


def _launch(server, config, body: dict, label: str = "campaign") -> dict[str, Any]:
    from ..core.campaign import Campaign

    refused = _busy(server, config)
    if refused:
        return refused
    jobs = int(body.get("jobs") or 1)
    budget = body.get("budget")
    if budget:
        from ..exec.runner import _parse_duration

        try:
            config.budget.execution_s = _parse_duration(budget)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad budget {budget!r}"}

    command = " ".join(config.targets[0].command) if config.targets else "?"
    # Installing is something the user agreed to on the review screen, which lists what will be
    # downloaded; a request that does not say so installs nothing and the campaign says what is missing.
    install = bool(body.get("install_missing"))
    to_install = missing_generators(config) if install else []

    demo = getattr(server, "spreadex_demo", None)

    def work(job):
        installed = []
        if demo:
            # The guided demo asks nothing of the user: the same installer the CLI demo uses, which
            # falls back to the bundled seeds when it cannot install (offline, say).
            from ..demo import prepare_generators
            job.log("Preparing the demo's generators (first time only; the run's budget has not started).")
            prepare_generators(config, log=job.log)
        elif to_install:
            mgr = GeneratorManager()
            job.log(f"Installing {len(to_install)} generator(s) before the run "
                    f"(first time only; the run's time budget has not started).")
            for gid in to_install:
                job.log(f"- {mgr.get(gid).name}")
                mgr.install(gid, log=job.log)
                installed.append(gid)
        job.log(f"Running: {command}")
        campaign = Campaign(config, log=job.log, stop_event=stop, origin="ui")
        result = campaign.run(jobs=jobs)
        return {
            "installed": installed,
            "run_id": result.run_id,
            "executed": result.executed,
            "verdicts": result.verdicts,
            "new_signatures": len(result.new_signatures),
        }

    import threading
    stop = threading.Event()
    try:
        server.spreadex_jobs.start("run", label, work)
    except RuntimeError as exc:
        return {"ok": False, "conflict": True, "error": str(exc)}
    server.spreadex_stop = stop
    # Echo the command back so the UI can show what it just set going.
    return {"ok": True, "command": command, "installing": to_install}


def cancel_run(server, run_id: str) -> dict[str, Any]:
    """Stop the running campaign after its current input. Works for a run this server
    started (via its stop event) and for one started elsewhere (via the cancel file)."""
    from ..core.lock import active_run, cancel_file

    state_dir = server.spreadex_config.state_dir
    info = active_run(state_dir)
    if not info or info.get("run_id") != run_id:
        return {"ok": False, "error": f"{run_id} is not running"}
    stop = getattr(server, "spreadex_stop", None)
    if stop is not None and server.spreadex_jobs.busy:
        stop.set()
    path = cancel_file(state_dir, run_id)
    if path.parent.is_dir():
        path.write_text("")
    return {"ok": True, "run_id": run_id, "cancelling": True}


def delete_run(server, run_id: str) -> dict[str, Any]:
    """Permanently forget a run, reclaiming results and inputs only it used."""
    from ..core.lock import active_run
    from ..corpus.store import CorpusStore

    state_dir = server.spreadex_config.state_dir
    info = active_run(state_dir)
    if info is not None and info.get("run_id") in (run_id, None):
        return {"ok": False, "conflict": True,
                "error": f"{run_id} is running; cancel it before deleting it"}
    if not state_dir.is_dir():
        return {"ok": False, "error": f"no run {run_id!r}"}
    with CorpusStore(state_dir) as store:
        try:
            out = store.delete_run(run_id)
        except KeyError:
            return {"ok": False, "error": f"no run {run_id!r}"}
    return {"ok": True, **out}


def rerun(server, run_id: str, body: dict) -> dict[str, Any]:
    """Run again with the configuration that run recorded, not whatever is saved now."""
    import json
    import tempfile

    state_dir = server.spreadex_config.state_dir
    manifest = state_dir / "runs" / run_id / "manifest.json"
    try:
        raw = json.loads(manifest.read_text()).get("config")
    except (OSError, ValueError):
        raw = None
    if not raw:
        return {"ok": False, "error": f"{run_id} has no recorded configuration to re-run"}
    # Relative paths in the config resolve against its file's folder, so the copy is read
    # from the project root -- and removed as soon as it has been parsed.
    root = server.spreadex_config.project_root
    fd, tmp = tempfile.mkstemp(prefix=".spreadex-rerun-", suffix=".yaml", dir=root)
    try:
        with os.fdopen(fd, "w") as fh:
            yaml.safe_dump(raw, fh)
        config = load_config(Path(tmp))
    except ConfigError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        os.unlink(tmp)
    return _launch(server, config, {**body, "install_missing": True}, label=f"re-run of {run_id}")


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


# ------------------------------------------------------------------ replay one input

def replay_input(config, run_id: str, blob_hash: str) -> dict[str, Any]:
    """Run one recorded input again against the project's CURRENT command and oracle, and say whether
    the original result came back. Nothing is written: a replay is an observation, not a new run.

    It uses the same Target, input naming (extension) and oracle a campaign uses, so "reproduced"
    means what it would mean in a campaign. A flaky or fixed bug shows up as "not reproduced".
    """
    from ..corpus.store import CorpusStore
    from ..exec.inputs import InputFiles
    from ..exec.oracle import make_oracle
    from ..exec.runner import run_one

    if not blob_hash or not blob_hash.isalnum():
        return {"ok": False, "error": "bad input hash"}
    if not config.targets:
        return {"ok": False, "error": "this project has no command to run yet"}
    with CorpusStore(config.state_dir) as store:
        rows = store.conn.execute(
            "SELECT verdict, signature, duration_ms FROM executions WHERE run_id=? AND blob_hash=?",
            (run_id, blob_hash)).fetchall()
        if not rows:
            return {"ok": False, "error": "that input was not executed in this run"}
        path = store.blob_path(blob_hash)
        if not path.exists():
            return {"ok": False, "error": "the input file is no longer in the corpus"}
        original = {"verdict": rows[0]["verdict"], "signature": rows[0]["signature"],
                    "duration_ms": max((r["duration_ms"] or 0) for r in rows)}
        files = InputFiles(config.input_extension)
        try:
            observations = [run_one(t, files.path(blob_hash, path), input_hash=blob_hash) for t in config.targets]
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc).split("\n")[0]}
        judgement = make_oracle(config.oracle).judge(observations)
    first = observations[0]
    return {
        "ok": True, "original": original,
        "replay": {"verdict": judgement.verdict.value, "signature": judgement.signature,
                   "duration_ms": max(o.duration_ms for o in observations), "exit_code": first.exit_code,
                   "signal": first.signal, "timed_out": first.timed_out,
                   "stderr": (first.stderr_preview or "")[:1500]},
        "reproduced": judgement.verdict.value == original["verdict"],
    }


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

    # The command ran, but the system did not start: say so, rather than showing it as a run
    # with an unusual exit code that step 4 would later call a crash on every input.
    from ..exec.setup_check import setup_failure
    problem = setup_failure(obs, target)
    if problem:
        return {"ok": False, "setup": True, "command": rendered,
                "error": f"The command ran, but your system did not start: {problem}. "
                         f"Check the paths in the command; relative paths are read from the project folder."}

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


# ------------------------------------------------------------ guided demo

def demo_status(server) -> dict[str, Any]:
    """Is there a demo workspace, does it have campaigns, and is its Workbench up?"""
    from ..core.lock import active_run
    from ..demo import demo_root
    from . import registry

    root = demo_root()
    state = root / ".spreadex"
    has_runs = False
    if (state / "corpus.db").is_file():
        from ..corpus.store import CorpusStore
        with CorpusStore(state) as store:
            has_runs = store.latest_run_id() is not None
    live = registry.find_live(root)
    # A few of the demo's real seed inputs, for the guide to show what the grammar describes.
    samples = []
    seeds = root / "seeds"
    if seeds.is_dir():
        for f in sorted(seeds.iterdir())[:20]:
            text = f.read_text(errors="replace").strip().splitlines()
            if text and 0 < len(text[0]) <= 40:
                samples.append(text[0])
            if len(samples) == 4:
                break
    from ..demo import grammar_excerpt
    bnf = root / "calc.bnf"
    # The demo's Fandango constraint, as written, for the guide to show: the `where` rule itself,
    # not the imports above it.
    fan = root / "spec" / "constraints.fan"
    constraint = next((l.strip() for l in fan.read_text().splitlines()
                       if l.strip().startswith("where ")), "") if fan.is_file() else ""
    return {"exists": (root / "spreadex.yaml").is_file(), "has_runs": has_runs, "samples": samples,
            "grammar_rules": grammar_excerpt(bnf) if bnf.is_file() else [],
            "constraint": constraint,
            # The same rule in plain language: what the user states, and what the guide shows.
            "rule": next((l.strip() for l in (root / "spec" / "rules.md").read_text().splitlines() if l.strip()), "")
                    if (root / "spec" / "rules.md").is_file() else "",
            "active": active_run(state) is not None if state.is_dir() else False,
            "live": live is not None, "is_demo": bool(getattr(server, "spreadex_demo", None))}


def demo_open(server, body: dict, return_url: str) -> dict[str, Any]:
    """Prepare the managed demo workspace and hand back its Workbench's address.

    The demo is a separate project under SpreadEx's own state, served by its own Workbench (own port,
    own token) from this process. Nothing about the project this Workbench serves is touched.
    """
    from ..core.config import load_config
    from ..core.lock import RunInProgress
    from ..demo import demo_root, ensure, reset
    from . import registry
    from .server import project_token, start_background

    root = demo_root()
    try:
        if body.get("reset"):
            reset(root)
        else:
            ensure(root)
    except RunInProgress:
        return {"ok": False, "conflict": True,
                "error": "The demo has a campaign running. Open it, or cancel it before starting fresh."}
    except OSError as exc:
        return {"ok": False, "error": f"could not prepare the demo in {root}: {exc}"}
    config = load_config(root / "spreadex.yaml")
    live = registry.find_live(root)
    if live:
        url = f"http://{live['host']}:{live['port']}/?token={project_token(config)}"
    else:
        url = start_background(config, embedded_in=server.spreadex_config.project_root,
                               spreadex_demo={"return_url": return_url})
    return {"ok": True, "url": url + ("&tour=1" if body.get("tour", True) else ""), "root": str(root)}


# ------------------------------------------------------------------ bundled examples

def examples_status(server) -> dict[str, Any]:
    """The bundled examples other than the guided demo (which has /api/demo): what each needs,
    and whether it has been opened before."""
    from .. import examples, runtimes
    from . import registry

    out = []
    for ex in examples.EXAMPLES.values():
        if ex.name == "minicalc":
            continue
        root = examples.root(ex.name)
        state = root / ".spreadex"
        has_runs = False
        if (state / "corpus.db").is_file():
            from ..corpus.store import CorpusStore
            with CorpusStore(state) as store:
                has_runs = store.latest_run_id() is not None
        out.append({
            "name": ex.name, "title": ex.title, "summary": ex.summary, "tags": list(ex.tags),
            "exists": (root / "spreadex.yaml").is_file(), "has_runs": has_runs,
            "live": registry.find_live(root) is not None,
            "runtimes": [{"name": r, "title": runtimes.get(r).title, "version": runtimes.get(r).version,
                          "installed": runtimes.verified(r) is not None} for r in ex.runtimes],
        })
    return {"examples": out}


def example_open(server, body: dict, return_url: str) -> dict[str, Any]:
    """Prepare a bundled example as its own project and hand back its Workbench's address.

    Downloads and verifies any pinned runtime first. The example is a separate project under
    SpreadEx's own state with its own Workbench; the project this Workbench serves is not touched.
    """
    from .. import examples, runtimes
    from ..core.config import load_config
    from ..core.lock import RunInProgress
    from . import registry
    from .server import project_token, start_background

    name = str(body.get("name") or "")
    try:
        ex = examples.get(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if ex.name == "minicalc":
        return {"ok": False, "error": "the guided demo opens with /api/demo/open"}
    log: list[str] = []
    try:
        for rt in ex.runtimes:
            runtimes.ensure(rt, log=log.append)
    except runtimes.RuntimeUnavailable as exc:
        return {"ok": False, "error": str(exc), "log": log}
    try:
        root = examples.reset(ex.name) if body.get("reset") else examples.ensure(ex.name)
    except RunInProgress:
        return {"ok": False, "conflict": True,
                "error": f"The {ex.title} example has a campaign running. Open it, or cancel it before starting fresh."}
    except OSError as exc:
        return {"ok": False, "error": f"could not prepare the {ex.title} example: {exc}"}
    config = load_config(root / "spreadex.yaml")
    live = registry.find_live(root)
    if live:
        url = f"http://{live['host']}:{live['port']}/?token={project_token(config)}"
    else:
        url = start_background(config, embedded_in=server.spreadex_config.project_root,
                               spreadex_example={"name": ex.name, "return_url": return_url})
    return {"ok": True, "url": url + "&open=setup", "root": str(root), "log": log}
