"""Bundled example projects, each a separate managed project under SpreadEx's own state.

Opening an example never touches the project the user is working in: the example lives in its own
folder (``~/.spreadex/demo`` for MiniCalc, ``~/.spreadex/examples/<name>`` for the others), with
its own spreadex.yaml and campaign history, served by its own Workbench.

  minicalc   the guided tutorial; delegates to spreadex.demo, which is unchanged
  rhino      a real JavaScript engine (public Rhino release, pinned) with three generators
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import demo


@dataclass(frozen=True)
class Example:
    name: str
    title: str
    summary: str
    #: Pinned runtimes the example's command needs (spreadex/runtimes.py).
    runtimes: tuple[str, ...] = ()
    #: Generators that must be installed for a campaign (replayed ones need nothing).
    generators: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default=())


EXAMPLES: dict[str, Example] = {
    "minicalc": Example("minicalc", "MiniCalc", "Guided tutorial: a small expression language.",
                        tags=("tutorial",)),
    "rhino": Example("rhino", "Rhino", "A real JavaScript engine (public Rhino 1.9.1), three generators.",
                     runtimes=("rhino",), generators=("fandango", "grammarinator"), tags=("java", "showcase")),
}


def get(name: str) -> Example:
    try:
        return EXAMPLES[name]
    except KeyError:
        raise ValueError(f"unknown example {name!r}; known: {', '.join(EXAMPLES)}") from None


def source_dir(name: str) -> Path:
    get(name)
    return demo.source_dir() if name == "minicalc" else Path(demo.__file__).resolve().parent / name


def root(name: str) -> Path:
    get(name)
    if name == "minicalc":
        return demo.demo_root()
    from .api.registry import home

    return home() / "examples" / name


def _files(src: Path):
    for f in sorted(src.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and not f.name.startswith("."):
            yield f


def ensure(name: str, at: Path | None = None) -> Path:
    """The example's project, written on first use and repaired after that.

    Missing shipped files are restored; existing files -- which the user may have edited -- and
    the example's campaign history are never overwritten.
    """
    if name == "minicalc":
        return demo.ensure(at)
    dest = Path(at or root(name))
    src = source_dir(name)
    for f in _files(src):
        target = dest / f.relative_to(src)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    return dest


def reset(name: str, at: Path | None = None) -> Path:
    """Start the example over: its files and its whole history. Refused while it is running."""
    if name == "minicalc":
        return demo.reset(at)
    from .core.lock import RunInProgress, active_run

    dest = Path(at or root(name))
    info = active_run(dest / ".spreadex")
    if info is not None:
        raise RunInProgress(info)
    if dest.exists():
        shutil.rmtree(dest)
    return ensure(name, dest)
