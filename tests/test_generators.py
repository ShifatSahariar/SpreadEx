"""Generator catalog and manager.

Installation is deterministic: the catalog states package names and pins, and a
package manager acts on them. Nothing here guesses, so all of it is testable
offline except the one test explicitly marked as needing the network.
"""

from __future__ import annotations

import pytest

from spreadex.generators import GeneratorError, GeneratorManager, load_catalog


def test_catalog_loads_and_is_complete():
    catalog = load_catalog()
    assert {"fuzzingbook", "fandango", "grammarinator", "isla"} <= set(catalog)
    for gen in catalog.values():
        assert gen.name and gen.summary and gen.homepage and gen.license
        if gen.install.get("type") == "none":
            # Replay-only in this version (Fuzz4All): nothing to install, and it says why.
            assert gen.install.get("reason") and gen.capabilities.get("recorded")
            continue
        assert gen.install.get("type") == "python"
        assert gen.install.get("package")
        assert gen.check.get("type") in {"command", "python_import"}
        assert gen.capabilities.get("grammar")


def test_catalog_records_the_isla_pkg_resources_workaround():
    """ISLa cannot be imported without an older setuptools. That fact belongs in
    the catalog, versioned and reviewable -- not in a model's guess at runtime."""
    isla = load_catalog()["isla"]
    assert isla.extra_packages == ["setuptools<81"]
    assert "pkg_resources" in isla.notes


def test_generators_declare_distinct_grammar_dialects():
    """The portfolio is only meaningful if the generators differ."""
    catalog = load_catalog()
    dialects = {g.grammar_dialect for g in catalog.values()}
    assert len(dialects) == len(catalog), f"expected distinct dialects, got {dialects}"


def test_unknown_generator_names_the_known_ones(tmp_path):
    mgr = GeneratorManager(cache_dir=tmp_path)
    with pytest.raises(GeneratorError, match="Known generators"):
        mgr.get("nonesuch")


def test_environments_are_per_generator(tmp_path):
    mgr = GeneratorManager(cache_dir=tmp_path)
    assert mgr.env_dir("isla") != mgr.env_dir("fandango")
    assert mgr.env_dir("isla").is_relative_to(tmp_path)


def test_status_reports_not_installed_for_an_empty_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # hide any host installation
    mgr = GeneratorManager(cache_dir=tmp_path)
    st = mgr.status("fandango")
    assert not st.installed and st.where == ""


def test_ensure_refuses_to_install_implicitly(tmp_path, monkeypatch):
    """`spreadex run` must never silently install software. It reports what is
    missing and names the command that fixes it."""
    monkeypatch.setenv("PATH", str(tmp_path))
    mgr = GeneratorManager(cache_dir=tmp_path)
    with pytest.raises(GeneratorError, match="spreadex generators install"):
        mgr.ensure(["fandango"], auto_install=False)


def test_environment_hash_is_none_before_installation(tmp_path):
    assert GeneratorManager(cache_dir=tmp_path).environment_hash("isla") is None


@pytest.mark.network
def test_real_isolated_installation(tmp_path):
    """End to end against PyPI. Deselect with: -m 'not network'."""
    mgr = GeneratorManager(cache_dir=tmp_path)
    status = mgr.install("fuzzingbook", log=lambda *_: None)
    assert status.installed and status.where == "environment"
    assert mgr.environment_hash("fuzzingbook")
    receipt = tmp_path / "generators" / "fuzzingbook" / "receipt.json"
    assert receipt.exists()


def test_doctor_does_not_keep_a_second_opinion_about_what_can_generate():
    """A hardcoded "this one is a stub" list said Grammarinator could not
    generate for months after it could. Membership in ADAPTERS is the only
    claim, so there is nothing to go stale beside it."""
    from spreadex.cli import doctor
    from spreadex.generators.adapters import ADAPTERS

    from pathlib import Path

    source = Path(doctor.__file__).read_text()
    assert "_adapter_is_stub" not in source
    assert "grammarinator" not in source.lower(), "no generator is named in doctor's logic"
    assert "grammarinator" in ADAPTERS


def test_every_catalogued_generator_we_claim_to_drive_has_an_adapter():
    from spreadex.generators.adapters import ADAPTERS

    catalog = load_catalog()
    for gid in ADAPTERS:
        assert gid in catalog, f"{gid} has an adapter but is not in the catalog"
