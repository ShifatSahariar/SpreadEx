import pytest
import yaml

from spreadex.core.config import ConfigError, load_config, render_template


def write(tmp_path, body: str):
    p = tmp_path / "spreadex.yaml"
    p.write_text(body)
    return p


def test_template_is_valid_yaml_and_keeps_the_input_placeholder():
    # Regression: the template used str.format, and the literal {input} braces
    # in it collided with the format fields.
    text = render_template(["python3", "./parser.py", "{input}"])
    doc = yaml.safe_load(text)
    assert doc["sut"]["command"][-1] == "{input}"


def test_single_target(tmp_path):
    cfg = load_config(write(tmp_path, """
sut: {command: [./p, "{input}"]}
generators: []
corpus: {path: ./seeds}
"""))
    assert len(cfg.targets) == 1
    assert not cfg.is_differential
    assert cfg.oracle["type"] == "crash"


def test_multiple_targets_default_to_a_differential_oracle(tmp_path):
    cfg = load_config(write(tmp_path, """
sut:
  targets:
    - {name: a, command: [./a, "{input}"]}
    - {name: b, command: [./b, "{input}"]}
"""))
    assert cfg.is_differential
    assert cfg.oracle["type"] == "differential"


def test_explicitly_empty_generators_means_none(tmp_path):
    # Regression: `generators: []` fell back to the default because an empty
    # list is falsy, so a corpus-only project still tried to run fuzzingbook.
    cfg = load_config(write(tmp_path, """
sut: {command: [./p, "{input}"]}
generators: []
corpus: {path: ./seeds}
"""))
    assert cfg.generators == []


def test_absent_generators_key_uses_the_default(tmp_path):
    cfg = load_config(write(tmp_path, 'sut: {command: [./p, "{input}"]}\n'))
    assert cfg.generators == ["fuzzingbook"]


def test_duration_suffixes(tmp_path):
    cfg = load_config(write(tmp_path, """
sut: {command: [./p], timeout: 2m}
budget: {generation: 90s, execution: 1h}
"""))
    assert cfg.targets[0].limits.timeout_s == 120
    assert cfg.budget.generation_s == 90
    assert cfg.budget.execution_s == 3600


def test_config_hash_tracks_meaning_not_formatting(tmp_path):
    a = load_config(write(tmp_path, 'sut: {command: [./p, "{input}"]}\nseed: 1\n'))
    h1 = a.hash()
    b = load_config(write(tmp_path, '# a comment\nsut:\n  command: [./p, "{input}"]\nseed: 1\n'))
    assert b.hash() == h1
    c = load_config(write(tmp_path, 'sut: {command: [./p, "{input}"]}\nseed: 2\n'))
    assert c.hash() != h1


@pytest.mark.parametrize("body,msg", [
    ("generators: []\n", "missing required `sut:`"),
    ("sut: {}\n", "needs either `command:`"),
    ("sut:\n  targets:\n    - {name: a, command: [./a]}\noracle: {type: differential}\n",
     "needs at least two"),
    ("sut:\n  targets:\n    - {name: a, command: [./a]}\n    - {name: a, command: [./b]}\n",
     "duplicate target name"),
])
def test_configuration_errors_say_how_to_fix_them(tmp_path, body, msg):
    with pytest.raises(ConfigError, match=msg):
        load_config(write(tmp_path, body))


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError, match="spreadex init"):
        load_config(tmp_path / "nope.yaml")
