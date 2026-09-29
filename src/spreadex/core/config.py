"""spreadex.yaml -- the whole configuration surface, deliberately small."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..exec.runner import Target, _parse_duration

CONFIG_NAME = "spreadex.yaml"
STATE_DIR = ".spreadex"


class ConfigError(Exception):
    """Raised for a configuration problem the user can fix."""


@dataclass
class BudgetConfig:
    generation_s: float = 60.0
    execution_s: float = 60.0
    max_inputs: int | None = None


@dataclass
class Config:
    project_root: Path
    targets: list[Target]
    oracle: dict
    budget: BudgetConfig
    generators: list[str] = field(default_factory=lambda: ["fuzzingbook"])
    grammar: dict = field(default_factory=dict)
    signal: str = "cc"
    embedding: dict = field(default_factory=lambda: {"model": "tfidf"})
    seed: int = 42
    raw: dict = field(default_factory=dict)

    @property
    def state_dir(self) -> Path:
        return self.project_root / STATE_DIR

    @property
    def is_differential(self) -> bool:
        return len(self.targets) > 1

    def hash(self) -> str:
        """Stable hash of the semantic configuration, for the manifest."""
        payload = {
            "targets": [
                {"name": t.name, "command": t.command, "version": t.version,
                 "timeout_s": t.limits.timeout_s}
                for t in self.targets
            ],
            "oracle": self.oracle,
            "generators": sorted(self.generators),
            "signal": self.signal,
            "embedding": self.embedding,
            "seed": self.seed,
            "budget": {"generation_s": self.budget.generation_s,
                       "execution_s": self.budget.execution_s,
                       "max_inputs": self.budget.max_inputs},
        }
        blob = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(entry: dict, config_path: Path) -> dict:
    """Expand ${VAR} in a target's command.

    Paths to a built SUT differ per machine, so the config references an
    environment variable rather than hardcoding one. An unset variable is an
    error with the variable named -- never a silent empty string, which would
    produce a baffling "command not found".
    """
    command = entry.get("command")
    if not command:
        return entry

    expanded = []
    for part in command:
        if not isinstance(part, str):
            expanded.append(part)
            continue

        def sub(m):
            name = m.group(1)
            value = os.environ.get(name)
            if value is None:
                raise ConfigError(
                    f"{config_path}: environment variable ${{{name}}} is referenced by "
                    f"sut.command but is not set.\n"
                    f"  Fix: export {name}=... before running, or replace ${{{name}}} "
                    f"with a literal path."
                )
            return value

        expanded.append(_ENV_REF.sub(sub, part))
    return {**entry, "command": expanded}


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for spreadex.yaml, like git does for .git."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        cfg = candidate / CONFIG_NAME
        if cfg.is_file():
            return cfg
    return None


def load_config(path: Path | None = None) -> Config:
    path = Path(path) if path else find_config()
    if path is None:
        raise ConfigError(
            f"No {CONFIG_NAME} found in this directory or any parent.\n"
            f"  Fix: run `spreadex init` in your project root."
        )
    path = Path(path).resolve()
    if not path.is_file():
        raise ConfigError(
            f"No configuration file at {path}.\n"
            f"  Fix: run `spreadex init` in your project root, or pass -c <path>."
        )
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML:\n  {exc}") from exc

    if "sut" not in raw or raw["sut"] is None:
        raise ConfigError(
            f"{path}: missing required `sut:` section.\n"
            f"  Fix: add\n"
            f"    sut:\n"
            f"      command: [./your-parser, \"{{input}}\"]"
        )
    sut = raw["sut"]
    if not isinstance(sut, dict):
        raise ConfigError(f"{path}: `sut:` must be a mapping, not {type(sut).__name__}.")

    defaults = {"timeout": sut.get("timeout", 5), "memory_mb": sut.get("memory_mb", 2048)}

    if "targets" in sut:
        entries = sut["targets"]
        if not isinstance(entries, list) or not entries:
            raise ConfigError(f"{path}: `sut.targets` must be a non-empty list.")
    elif "command" in sut:
        entries = [{"name": sut.get("name", "sut"), **sut}]
    else:
        raise ConfigError(
            f"{path}: `sut:` needs either `command:` (single target) or "
            f"`targets:` (two or more, for differential testing)."
        )

    targets = []
    seen: set[str] = set()

    for i, entry in enumerate(entries):
        if "command" not in entry:
            raise ConfigError(f"{path}: sut.targets[{i}] is missing `command:`.")
        entry = _expand_env(entry, path)
        t = Target.from_config(entry, defaults, base_dir=path.parent)
        if t.name in seen:
            raise ConfigError(f"{path}: duplicate target name {t.name!r}; names must be unique.")
        seen.add(t.name)
        targets.append(t)

    oracle = raw.get("oracle") or {}
    if "type" not in oracle:
        # The sensible default: differential the moment there is something to
        # compare against, otherwise crash detection.
        oracle["type"] = "differential" if len(targets) > 1 else "crash"
    if oracle["type"] == "differential" and len(targets) < 2:
        raise ConfigError(
            f"{path}: `oracle.type: differential` needs at least two entries under `sut.targets`."
        )

    b = raw.get("budget") or {}
    budget = BudgetConfig(
        generation_s=_parse_duration(b.get("generation", 60)),
        execution_s=_parse_duration(b.get("execution", 60)),
        max_inputs=b.get("max_inputs"),
    )

    return Config(
        project_root=path.parent,
        targets=targets,
        oracle=oracle,
        budget=budget,
        # An explicitly empty list means "no generators" (corpus-only);
        # only an absent key falls back to the default.
        generators=list(raw["generators"] if "generators" in raw and raw["generators"] is not None
                        else ["fuzzingbook"]),
        grammar=raw.get("grammar") or {},
        signal=raw.get("selection_signal", raw.get("signal", "cc")),
        embedding=raw.get("embedding") or {"model": "tfidf"},
        seed=int(raw.get("seed", 42)),
        raw=raw,
    )


# Written verbatim with placeholder tokens rather than str.format, so that
# literal {input} braces in the template cannot collide with field names.
TEMPLATE = """\
# SpreadEx configuration. Everything runs locally; nothing is uploaded.
sut:
  # {input} is replaced with the path to each generated input.
  command: [__COMMAND__]
  timeout: 5s

  # For differential testing, replace `command:` above with two or more targets:
  # targets:
  #   - {name: rhino,   command: [java, -jar, rhino.jar, "{input}"]}
  #   - {name: graaljs, command: [js, "{input}"]}

oracle:
  type: __ORACLE__          # crash | differential
  # expected_exit_codes: [0]   # add 1 here if your SUT exits 1 on invalid input

# Where inputs come from. Use a corpus, generators, or both.
generators: [fuzzingbook]
# corpus:
#   path: ./seeds

grammar:
  source: __GRAMMAR__

budget:
  generation: 1m
  execution: 1m

selection_signal: cc    # cc (default) | random
embedding:
  model: tfidf          # tfidf (no extra deps) | unixcoder (needs spreadex[neural])

seed: 42
"""


def render_template(command: list[str], grammar: str = "grammar.g4", oracle: str = "crash") -> str:
    cmd = ", ".join(json.dumps(c) for c in command)
    return (
        TEMPLATE.replace("__COMMAND__", cmd)
        .replace("__GRAMMAR__", grammar)
        .replace("__ORACLE__", oracle)
    )
