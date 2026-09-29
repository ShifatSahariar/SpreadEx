"""Deterministic generator installation. No LLM, no invented shell commands.

Installing Grammarinator is a solved problem: it is a PyPI package with a known
name. A model guessing at install commands would make SpreadEx less
reproducible, less secure, harder to debug, dependent on network APIs and
impossible to artifact-evaluate. So the catalog states the facts and a package
manager acts on them.

Each generator gets its OWN environment under ~/.cache/spreadex/generators/,
so one generator's dependency pins cannot break another's -- and neither can
break SpreadEx itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CATALOG_DIR = Path(__file__).with_name("catalog")
DEFAULT_CACHE = Path(
    os.environ.get("SPREADEX_CACHE", Path.home() / ".cache" / "spreadex")
)


class GeneratorError(Exception):
    """A generator problem the user can act on."""


@dataclass(frozen=True)
class Generator:
    id: str
    name: str
    summary: str = ""
    homepage: str = ""
    license: str = ""
    notes: str = ""
    install: dict = field(default_factory=dict)
    check: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)

    @property
    def package(self) -> str:
        return self.install.get("package", self.id)

    @property
    def requirement(self) -> str:
        return f"{self.package}{self.install.get('version', '')}"

    @property
    def extra_packages(self) -> list[str]:
        """Packages a generator needs to import but does not declare itself.

        Recording these in the catalog keeps a known-broken upstream usable
        without guesswork: the fix is reviewable, versioned and reproducible.
        """
        return list(self.install.get("extra_packages") or [])

    @property
    def grammar_dialect(self) -> str:
        return self.capabilities.get("grammar", "unknown")

    @property
    def supports_constraints(self) -> bool:
        return bool(self.capabilities.get("constraints", False))


def load_catalog(catalog_dir: Path | None = None) -> dict[str, Generator]:
    d = Path(catalog_dir or CATALOG_DIR)
    out: dict[str, Generator] = {}
    for path in sorted(d.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        gid = data.get("id") or path.stem
        out[gid] = Generator(
            id=gid,
            name=data.get("name", gid),
            summary=data.get("summary", ""),
            homepage=data.get("homepage", ""),
            license=data.get("license", ""),
            notes=data.get("notes", ""),
            install=data.get("install") or {},
            check=data.get("check") or {},
            capabilities=data.get("capabilities") or {},
        )
    return out


@dataclass
class Status:
    generator: Generator
    installed: bool
    version: str | None = None
    where: str = ""          # "environment" | "host" | ""
    detail: str = ""

    @property
    def id(self) -> str:
        return self.generator.id


class GeneratorManager:
    """Resolves, checks and installs generators into isolated environments."""

    def __init__(self, cache_dir: Path | None = None, catalog_dir: Path | None = None) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE)
        self.envs_dir = self.cache_dir / "generators"
        self.catalog = load_catalog(catalog_dir)

    # ------------------------------------------------------------- lookup

    def get(self, generator_id: str) -> Generator:
        try:
            return self.catalog[generator_id]
        except KeyError:
            known = ", ".join(sorted(self.catalog))
            raise GeneratorError(
                f"Unknown generator {generator_id!r}.\n  Known generators: {known}"
            ) from None

    def env_dir(self, generator_id: str) -> Path:
        return self.envs_dir / generator_id / "venv"

    def env_python(self, generator_id: str) -> Path:
        env = self.env_dir(generator_id)
        return env / ("Scripts" if os.name == "nt" else "bin") / "python"

    def env_bin(self, generator_id: str, executable: str) -> Path:
        env = self.env_dir(generator_id)
        return env / ("Scripts" if os.name == "nt" else "bin") / executable

    # -------------------------------------------------------------- status

    def status(self, generator_id: str) -> Status:
        """Is it usable, and from where? The environment wins over the host, so
        a campaign is not silently affected by whatever is on PATH."""
        gen = self.get(generator_id)
        check = gen.check or {}
        kind = check.get("type", "command")

        if self.env_dir(gen.id).exists():
            ok, version, detail = self._probe(gen, kind, check, in_env=True)
            if ok:
                return Status(gen, True, version, "environment", detail)

        ok, version, detail = self._probe(gen, kind, check, in_env=False)
        if ok:
            return Status(gen, True, version, "host", detail)
        return Status(gen, False, None, "", detail)

    def status_all(self) -> list[Status]:
        return [self.status(gid) for gid in sorted(self.catalog)]

    def _probe(self, gen: Generator, kind: str, check: dict, in_env: bool):
        try:
            if kind == "command":
                cmd = list(check.get("command") or [gen.id, "--version"])
                exe = str(self.env_bin(gen.id, cmd[0])) if in_env else shutil.which(cmd[0])
                if not exe or (in_env and not Path(exe).exists()):
                    return False, None, "not found"
                proc = subprocess.run([exe, *cmd[1:]], capture_output=True, timeout=30, check=False)
                text = (proc.stdout or b"").decode(errors="replace").strip() \
                    or (proc.stderr or b"").decode(errors="replace").strip()
                if proc.returncode != 0 and not text:
                    return False, None, f"exit {proc.returncode}"
                return True, (text.splitlines() or [None])[0], ""
            if kind == "python_import":
                module = check.get("module", gen.package)
                python = str(self.env_python(gen.id)) if in_env else sys.executable
                if in_env and not Path(python).exists():
                    return False, None, "environment missing"
                code = (
                    f"import importlib.metadata as m, {module};"
                    f"print(m.version({gen.package!r}))"
                )
                proc = subprocess.run([python, "-c", code], capture_output=True, timeout=60, check=False)
                if proc.returncode != 0:
                    return False, None, "import failed"
                return True, (proc.stdout or b"").decode(errors="replace").strip() or None, ""
            raise GeneratorError(f"Unsupported check type {kind!r} for generator {gen.id!r}.")
        except (OSError, subprocess.SubprocessError) as exc:
            return False, None, str(exc)

    def python_for(self, generator_id: str) -> str:
        """Interpreter to run this generator with: its own environment if it has
        one, otherwise the host. Keeps a campaign from silently picking up a
        different version that happens to be on PATH."""
        env_python = self.env_python(generator_id)
        return str(env_python) if env_python.exists() else sys.executable

    def executable_for(self, generator_id: str, executable: str) -> str | None:
        """Resolve a generator's CLI, preferring its isolated environment."""
        in_env = self.env_bin(generator_id, executable)
        if in_env.exists():
            return str(in_env)
        return shutil.which(executable)

    # ------------------------------------------------------------- install

    def install(self, generator_id: str, log=print, upgrade: bool = False) -> Status:
        gen = self.get(generator_id)
        if gen.install.get("type") != "python":
            raise GeneratorError(
                f"Generator {gen.id!r} declares install type "
                f"{gen.install.get('type')!r}, which this version cannot handle."
            )

        env = self.env_dir(gen.id)
        env.parent.mkdir(parents=True, exist_ok=True)
        uv = shutil.which("uv")

        if not env.exists():
            log(f"  creating isolated environment for {gen.name}")
            if uv:
                self._run([uv, "venv", str(env)], gen)
            else:
                self._run([sys.executable, "-m", "venv", str(env)], gen)

        requirements = [gen.requirement, *gen.extra_packages]
        pretty = ", ".join(requirements)
        log(f"  installing {pretty} from PyPI")
        if uv:
            cmd = [uv, "pip", "install", "--python", str(self.env_python(gen.id)), *requirements]
        else:
            cmd = [str(self.env_python(gen.id)), "-m", "pip", "install", "--quiet", *requirements]
        if upgrade:
            cmd.append("--upgrade")
        self._run(cmd, gen)

        status = self.status(gen.id)
        if not status.installed:
            raise GeneratorError(
                f"{gen.name} installed but its check still fails ({status.detail}).\n"
                f"  Environment: {env}\n"
                f"  Fix: inspect the environment, or remove it and retry."
            )
        self._write_receipt(gen, status)
        log(f"  {gen.name} ready ({status.version or 'version unknown'})")
        return status

    def _run(self, cmd: list[str], gen: Generator) -> None:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=900, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GeneratorError(f"Installing {gen.name} failed to start: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode(errors="replace").strip()[-1500:]
            offline = any(s in err.lower() for s in
                          ("temporary failure in name resolution", "network is unreachable",
                           "failed to establish a new connection", "could not resolve host"))
            hint = ("  No network connection was available and the package is not cached.\n"
                    f"  Fix: connect to the internet, or pre-install {gen.requirement} yourself.\n"
                    if offline else
                    f"  Fix: check the error above, or install {gen.requirement} manually.\n")
            raise GeneratorError(f"Installing {gen.name} failed.\n{hint}\n{err}")

    def _write_receipt(self, gen: Generator, status: Status) -> None:
        """Record what was installed, so a manifest can pin it."""
        receipt = {
            "id": gen.id,
            "package": gen.package,
            "version": status.version,
            "environment": str(self.env_dir(gen.id)),
            "environment_hash": self.environment_hash(gen.id),
        }
        path = self.env_dir(gen.id).parent / "receipt.json"
        path.write_text(json.dumps(receipt, indent=2))

    def environment_hash(self, generator_id: str) -> str | None:
        """Hash of the installed distribution list -- goes in the campaign manifest."""
        python = self.env_python(generator_id)
        if not python.exists():
            return None
        code = (
            "import importlib.metadata as m;"
            "print('\\n'.join(sorted(f'{d.metadata[\"Name\"]}=={d.version}' "
            "for d in m.distributions() if d.metadata['Name'])))"
        )
        try:
            proc = subprocess.run([str(python), "-c", code], capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return hashlib.sha256(proc.stdout).hexdigest()[:16]

    def ensure(self, generator_ids, log=print, auto_install: bool = False) -> dict[str, Status]:
        """Check the requested generators; optionally install what is missing.

        Installation is never implicit: `spreadex run` reports what is missing
        and stops, and only an explicit `spreadex generators install` (or
        --install) actually touches the machine.
        """
        out: dict[str, Status] = {}
        missing: list[str] = []
        for gid in generator_ids:
            st = self.status(gid)
            out[gid] = st
            if not st.installed:
                missing.append(gid)

        if missing and not auto_install:
            names = ", ".join(self.get(m).name for m in missing)
            raise GeneratorError(
                f"{len(missing)} selected generator(s) are not installed: {names}\n"
                f"  Fix: spreadex generators install {' '.join(missing)}"
            )
        for gid in missing:
            log(f"Installing {self.get(gid).name}...")
            out[gid] = self.install(gid, log=log)
        return out
