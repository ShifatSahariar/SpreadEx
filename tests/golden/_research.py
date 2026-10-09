"""Locate the research repository (the ICST 2026 replication package).

The golden tests import the research implementations directly -- not a copy --
so the tool is checked against the code that produced the published results.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _candidates():
    # An explicit SPREADEX_RESEARCH_REPO is AUTHORITATIVE: if it is set and
    # wrong, discovery must fail rather than quietly fall back to a repository
    # somewhere else on the machine -- otherwise the gate cannot be pinned.
    env = os.environ.get("SPREADEX_RESEARCH_REPO")
    if env:
        yield Path(env)
        return
    here = Path(__file__).resolve()
    # ../../../ from tests/golden/ is the directory holding both repositories.
    yield here.parents[3] / "Embedding-based-Diversity-Mapping" / "research"   # a clone of the research repo
    yield here.parents[3] / "SpreadEx-2026" / "research"
    yield Path.home() / "Documents" / "RESEARCH" / "SpreadEx-2026" / "research"


def find_research_root() -> Path | None:
    for c in _candidates():
        if (c / "PRIORATIZATION").is_dir():
            return c
    return None


RESEARCH_ROOT = find_research_root()

requires_research = pytest.mark.skipif(
    RESEARCH_ROOT is None,
    reason="research repository not found; set SPREADEX_RESEARCH_REPO to enable the golden suite",
)


def ensure_on_path() -> None:
    if RESEARCH_ROOT is not None and str(RESEARCH_ROOT) not in sys.path:
        sys.path.insert(0, str(RESEARCH_ROOT))
