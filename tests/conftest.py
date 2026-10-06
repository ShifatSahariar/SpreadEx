"""Test-wide isolation.

SpreadEx keeps a little per-user state (which Workbench runs where, and each project's access token)
under ~/.spreadex. Tests must never read or write the real one: a developer running the suite would
find their own servers listed, or tokens changed.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_spreadex_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SPREADEX_HOME", str(tmp_path_factory.mktemp("spreadex_home")))
