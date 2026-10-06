"""The bundled demo project: a real system under test that we own.

Shipped as package data so it is reachable from a wheel, which `examples/` is
not -- the README used to tell people to `cd examples/toy-parser`, a directory
that only exists in a git checkout.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: Everything copied into a new demo directory. Named explicitly rather than
#: globbed so a stray file in the source tree cannot end up in someone's
#: project.
DEMO_FILES = ("calc.py", "calc.bnf", "spreadex.yaml", "README.md")

DEMO_SEEDS = "seeds"

#: Directories copied whole: the seed corpus and the generator-specific constraints.
DEMO_DIRS = (DEMO_SEEDS, "spec")


def source_dir() -> Path:
    return Path(__file__).resolve().parent / "project"


def materialize(destination: Path, force: bool = False) -> Path:
    """Copy the demo project into `destination` and return the directory.

    Refuses to write over an existing demo unless asked, because the whole
    point is that someone can edit calc.py and run again.
    """
    destination = Path(destination)
    src = source_dir()
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(
            f"{destination} already exists and is not empty.\n"
            f"  Fix: `spreadex run` inside it, or `spreadex demo --force` to start over."
        )
    destination.mkdir(parents=True, exist_ok=True)
    for name in DEMO_FILES:
        shutil.copy2(src / name, destination / name)
    for name in DEMO_DIRS:
        target = destination / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src / name, target)
    (destination / "calc.py").chmod(0o755)
    return destination


# ------------------------------------------------- the managed demo workspace

def demo_root() -> Path:
    """Where the Workbench's guided demo lives: under SpreadEx's own per-user state, never beside
    someone's project, and always the same place, so opening it twice does not make two copies."""
    from ..api.registry import home

    return home() / "demo"


def reset(root: Path | None = None) -> Path:
    """Start the demo over: its files and its whole history. Refused while a demo run is going."""
    from ..core.lock import RunInProgress, active_run

    root = Path(root or demo_root())
    info = active_run(root / ".spreadex")
    if info is not None:
        raise RunInProgress(info)
    if root.exists():
        shutil.rmtree(root)
    return materialize(root)


def ensure(root: Path | None = None) -> Path:
    """The demo workspace, written on first use and reused after that.

    A reused workspace is also repaired: any file or folder the demo ships that is missing is
    restored, so a demo written by an older SpreadEx (before `spec/constraints.fan` existed, say)
    cannot fail on a path its own spreadex.yaml names. Existing files are never overwritten.
    """
    root = Path(root or demo_root())
    if not (root / "spreadex.yaml").is_file():
        return materialize(root, force=True)
    src = source_dir()
    for name in DEMO_FILES:
        if not (root / name).exists():
            shutil.copy2(src / name, root / name)
    for name in DEMO_DIRS:
        for f in (src / name).rglob("*"):
            target = root / f.relative_to(src)
            if f.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
    return root


def grammar_excerpt(path: Path, limit: int = 2) -> list[str]:
    """Two rules of the demo grammar, exactly as written, each on one line.

    For the guided demo to show what a grammar IS before what it produces: the top-level rule, and the
    first rule with parentheses (it explains inputs like `((((1))))`). Read from the file, never typed
    out by hand, so the guide cannot drift from the grammar that actually runs.
    """
    rules: list[list[str]] = []
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if "::=" in line and not line[0].isspace():
            rules.append([line.strip()])
        elif rules and line.lstrip().startswith("|"):
            rules[-1].append(line.strip())
    flat = [" ".join(r) for r in rules if not r[0].startswith("<start>")]
    if not flat:
        return []
    picked = [flat[0]]
    nested = next((r for r in flat[1:] if '"("' in r), None)
    if nested:
        picked.append(nested)
    return picked[:limit]


def prepare_generators(config, log=print) -> None:
    """Install the demo's generators; drop only the ones that cannot be installed.

    The demo is the one place installation is implicit, because the whole promise is "this just
    works". It is still the deterministic catalog doing the installing, into isolated
    environments, and it says so. A generator that will not install here (no network, a build
    failure) is dropped with the reason; the others still run, and with none left the campaign
    runs on the bundled seed inputs -- the same pipeline, with less to compare.
    """
    from ..generators import GeneratorError, GeneratorManager

    if not config.generators:
        return
    mgr = GeneratorManager()
    kept = []
    for gid in list(config.generators):
        try:
            mgr.ensure([gid], log=lambda m: log(f"  {m}"), auto_install=True)
            kept.append(gid)
        except (GeneratorError, OSError) as exc:
            log(f"\n  Could not install {gid}: {exc}")
            log(f"  Continuing without {gid}.\n")
    if not kept:
        log("  Running on the bundled seed inputs instead. The pipeline is the same;")
        log("  there is simply less to prioritize.\n")
    config.generators = kept
