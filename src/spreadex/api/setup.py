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
