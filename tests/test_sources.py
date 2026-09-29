"""Grammar resolution and environment expansion."""

import pytest

from spreadex.core.config import ConfigError, load_config
from spreadex.core.sources import grammar_for


def write(tmp_path, body):
    p = tmp_path / "spreadex.yaml"
    p.write_text(body)
    return p


def test_per_generator_grammars(tmp_path):
    """Generators speak different dialects, so each may have its own file."""
    cfg = load_config(write(tmp_path, """
sut: {command: [./p, "{input}"]}
generators: [fuzzingbook, fandango, isla]
grammar:
  fuzzingbook: g/rhino.py
  fandango: g/rhino.fan
  isla: g/rhino.bnf
"""))
    assert grammar_for(cfg, "fandango").name == "rhino.fan"
    assert grammar_for(cfg, "isla").name == "rhino.bnf"


def test_single_source_applies_to_all(tmp_path):
    cfg = load_config(write(tmp_path, """
sut: {command: [./p, "{input}"]}
generators: [fuzzingbook]
grammar: {source: g/shared.bnf}
"""))
    assert grammar_for(cfg, "fuzzingbook").name == "shared.bnf"


def test_per_generator_entry_wins_over_source(tmp_path):
    cfg = load_config(write(tmp_path, """
sut: {command: [./p, "{input}"]}
grammar: {source: g/shared.bnf, fandango: g/special.fan}
"""))
    assert grammar_for(cfg, "fandango").name == "special.fan"
    assert grammar_for(cfg, "isla").name == "shared.bnf"


def test_missing_grammar_is_none_not_a_guess(tmp_path):
    cfg = load_config(write(tmp_path, 'sut: {command: [./p, "{input}"]}\n'))
    assert grammar_for(cfg, "fandango") is None


def test_environment_variables_expand_in_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_JAR", "/opt/sut.jar")
    cfg = load_config(write(tmp_path, """
sut: {command: [java, -cp, "${MY_JAR}", Main, "{input}"]}
"""))
    assert "/opt/sut.jar" in cfg.targets[0].command


def test_unset_variable_names_itself(tmp_path, monkeypatch):
    """Silently expanding to "" would produce a baffling command-not-found."""
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    with pytest.raises(ConfigError, match="NOT_SET_ANYWHERE"):
        load_config(write(tmp_path, """
sut: {command: [java, -cp, "${NOT_SET_ANYWHERE}", Main]}
"""))
