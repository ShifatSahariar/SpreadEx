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


# --------------------------------------- the keys the wizard's Advanced section writes

import pytest as _pytest

from spreadex.core.config import ConfigError as _ConfigError, load_config as _load


def _cfg(tmp_path, sut_yaml):
    f = tmp_path / "spreadex.yaml"
    f.write_text(f"sut:\n{sut_yaml}generators: []\ncorpus: {{path: .}}\n")
    return f


def test_working_directory_environment_stdin_and_memory_reach_the_target(tmp_path):
    t = _load(_cfg(tmp_path,
        '  command: ["echo"]\n  cwd: work\n  input_mode: stdin\n  memory_mb: 512\n'
        '  env:\n    LANG: C.UTF-8\n    LEVEL: 3\n')).targets[0]
    assert t.cwd == "work" and t.input_mode == "stdin" and t.limits.memory_mb == 512
    assert t.env == {"LANG": "C.UTF-8", "LEVEL": "3"}, "numbers become strings"


@_pytest.mark.parametrize("sut_yaml, expect", [
    ('  command: ["x"]\n  env: [A, B]\n', "env must be a mapping"),
    ('  command: ["x"]\n  cwd: 12\n', "cwd must be a path string"),
    ('  command: ["x"]\n  memory_mb: lots\n', "memory_mb must be a positive whole number"),
    ('  command: ["x"]\n  memory_mb: 0\n', "memory_mb must be a positive whole number"),
    ('  command: ["x"]\n  timeout: soon\n', "timeout is not a duration"),
])
def test_a_malformed_option_is_refused_with_a_message_that_says_what_to_write(tmp_path, sut_yaml, expect):
    with _pytest.raises(_ConfigError) as exc:
        _load(_cfg(tmp_path, sut_yaml))
    assert expect in str(exc.value), str(exc.value)


def test_the_message_names_the_target_when_there_are_several(tmp_path):
    with _pytest.raises(_ConfigError) as exc:
        _load(_cfg(tmp_path,
            '  targets:\n    - {name: a, command: ["x"]}\n    - {name: b, command: ["y"], env: [1]}\n'))
    assert "sut.targets[1].env" in str(exc.value)
