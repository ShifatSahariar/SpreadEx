"""What ships, and what a stranger gets when they install it.

The acceptance criterion for v0.1 is a developer with no knowledge of this
research installing the tool and getting a real campaign. These tests guard
the parts of that which are checkable without a network.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_the_demo_ships_as_package_data(pyproject):
    """examples/ does not ship in a wheel, which is why the demo lives in the
    package. If this mapping is lost, `spreadex demo` breaks for everyone who
    installed rather than cloned -- and for nobody who develops here."""
    data = pyproject["tool"]["setuptools"]["package-data"]
    assert "spreadex.demo" in data
    patterns = data["spreadex.demo"]
    assert any("project/*" in p for p in patterns)
    assert any("seeds" in p for p in patterns), "the seed corpus too"


def test_every_non_python_thing_the_tool_needs_is_declared(pyproject):
    data = pyproject["tool"]["setuptools"]["package-data"]
    for package in ("spreadex.corpus", "spreadex.generators", "spreadex.api",
                    "spreadex.demo"):
        assert package in data, f"{package} ships files that are not .py"


def test_the_sdist_carries_what_someone_would_verify_with():
    manifest = (ROOT / "MANIFEST.in").read_text()
    for needed in ("LICENSE", "examples", "tests"):
        assert needed in manifest, needed
    assert "prune **/.spreadex" in manifest, "never ship a developer's corpus"


def test_the_install_stays_small(pyproject):
    """~50 MB, not ~2.5 GB. torch is an extra and must stay one: it is the
    single biggest adoption barrier available to us."""
    deps = " ".join(pyproject["project"]["dependencies"]).lower()
    for heavy in ("torch", "transformers", "pandas"):
        assert heavy not in deps, f"{heavy} belongs in an extra, not the base install"
    assert "torch" in " ".join(pyproject["project"]["optional-dependencies"]["neural"])


def test_metadata_is_complete_enough_to_publish(pyproject):
    project = pyproject["project"]
    assert project["license"] == "MIT" and project["license-files"] == ["LICENSE"]
    assert (ROOT / "LICENSE").is_file()
    assert project["urls"]["Repository"]
    assert any(c.startswith("Development Status") for c in project["classifiers"])
    assert project["authors"]


def test_the_release_workflow_does_not_publish_on_its_own():
    """Prepared for distribution, published by a human. A tag must not be able
    to put anything on PyPI by itself."""
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "if: false" in wf, "the PyPI job stays disabled until a maintainer enables it"
    assert "draft: true" in wf, "the GitHub release is a draft"
    assert "password:" not in wf and "PYPI_TOKEN" not in wf, "no token in CI"


def test_nothing_in_the_package_points_at_a_development_machine():
    """A path into someone's home directory in shipped code means the tool
    works on exactly one computer."""
    offenders = []
    for path in (ROOT / "src").rglob("*"):
        if path.suffix not in (".py", ".yaml", ".html", ".js", ".css", ".bnf", ".sql"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("/Users/", "ClusGram", "SpreadEx-2026"):
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert not offenders, offenders


# ------------------------------------------------------------ documentation

def test_the_subject_matrix_only_ticks_what_was_verified():
    """A tick that means 'code exists' is how a tool gets a reputation for not
    working. Every one must carry evidence."""
    text = (ROOT / "docs" / "SUBJECTS.md").read_text()
    assert "Last verified:" in text
    for row in [ln for ln in text.splitlines() if ln.startswith("| **") and "✓" in ln]:
        cells = [c.strip() for c in row.split("|")]
        assert cells[-2], f"a ✓ row with no evidence column: {row}"


def test_the_readme_does_not_point_at_a_directory_a_wheel_lacks():
    """`cd examples/toy-parser` only works in a git checkout, and the quick
    start is read mostly by people who installed."""
    quick = (ROOT / "README.md").read_text().split("## Commands")[0]
    assert "cd examples/" not in quick
    assert "spreadex demo" in quick


def test_async_wizard_steps_cannot_paint_over_a_later_step():
    """Clicking through faster than a fetch returns used to leave the screen a
    step behind while the state had already moved on. Guarded by a render
    token, which both fetching steps must honour."""
    app = (ROOT / "src" / "spreadex" / "api" / "static" / "app.js").read_text()
    assert "let RENDER = 0" in app
    assert "const mine = ++RENDER" in app
    for step in ("stepGrammar", "stepGenerators"):
        assert f"async function {step}(current = () => true)" in app, step
    assert app.count("if (!current()) return;") >= 2, "each must bail after its await"
