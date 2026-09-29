"""Guard: a skipped gate must never look like a passing gate.

The golden suite skips when the research repository is absent, which is correct
for someone who installed only the tool -- but catastrophic in CI, where a
silent skip would let a divergence ship. Setting SPREADEX_REQUIRE_GOLDEN=1
turns any skip into a failure.
"""

from __future__ import annotations

import os

import pytest

from _research import RESEARCH_ROOT, ensure_on_path

REQUIRED = os.environ.get("SPREADEX_REQUIRE_GOLDEN") == "1"


def test_research_repository_is_available():
    if not REQUIRED:
        if RESEARCH_ROOT is None:
            pytest.skip("research repository not found (set SPREADEX_REQUIRE_GOLDEN=1 to require it)")
        return
    assert RESEARCH_ROOT is not None, (
        "SPREADEX_REQUIRE_GOLDEN=1 but the research repository was not found.\n"
        "  Fix: set SPREADEX_RESEARCH_REPO=/path/to/SpreadEx-2026/research"
    )


def test_every_research_function_imports():
    """If any reference implementation cannot be imported, the gate is not armed."""
    if not REQUIRED and RESEARCH_ROOT is None:
        pytest.skip("research repository not found")
    ensure_on_path()
    import importlib

    from conftest import _RESEARCH_FUNCS

    broken = {}
    for name, (module_path, attr) in _RESEARCH_FUNCS.items():
        try:
            getattr(importlib.import_module(module_path), attr)
        except ImportError as exc:
            broken[name] = str(exc)

    if broken and not REQUIRED:
        pytest.skip(f"research dependencies unavailable: {broken}")
    assert not broken, (
        f"the golden gate is NOT armed; these reference implementations could not be imported: "
        f"{broken}\n  Fix: pip install -e '.[golden]'"
    )
