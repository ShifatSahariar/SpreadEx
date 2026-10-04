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
    seeds = destination / DEMO_SEEDS
    if seeds.exists():
        shutil.rmtree(seeds)
    shutil.copytree(src / DEMO_SEEDS, seeds)
    (destination / "calc.py").chmod(0o755)
    return destination
