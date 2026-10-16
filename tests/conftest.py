"""Test-wide isolation.

SpreadEx keeps a little per-user state (which Workbench runs where, and each project's access token)
under ~/.spreadex. Tests must never read or write the real one: a developer running the suite would
find their own servers listed, or tokens changed.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_spreadex_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SPREADEX_HOME", str(tmp_path_factory.mktemp("spreadex_home")))


@pytest.fixture(autouse=True)
def _tfidf_by_default(monkeypatch):
    """Campaigns in tests build their diversity map with TF-IDF unless a test asks otherwise.

    The product default is UniXcoder, which would download a 500 MB model and embed every input
    through a transformer; tests that are about the embedding choice set it explicitly.
    """
    monkeypatch.setenv("SPREADEX_DEFAULT_EMBEDDING", "tfidf")
