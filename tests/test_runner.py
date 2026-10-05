import sys

import pytest

from spreadex.exec.runner import Limits, Target, run_one


def make_sut(tmp_path, body: str):
    p = tmp_path / "sut.py"
    p.write_text(body)
    return p


def test_relative_command_resolves_against_the_project_root(tmp_path):
    # Regression: the child runs in a scratch directory, so `./sut.py` resolved
    # against the wrong cwd and EVERY input looked like a crash.
    make_sut(tmp_path, "import sys; print('ran', sys.argv[1])")
    t = Target("sut", [sys.executable, "./sut.py", "{input}"], base_dir=tmp_path,
               limits=Limits(timeout_s=10))
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    o = run_one(t, inp)
    assert o.exit_code == 0, o.stderr_preview
    assert "ran" in (o.stdout_preview or "")


def test_input_path_is_appended_when_no_placeholder(tmp_path):
    make_sut(tmp_path, "import sys; print(len(sys.argv))")
    t = Target("sut", [sys.executable, str(tmp_path / "sut.py")], limits=Limits(timeout_s=10))
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    assert "2" in (run_one(t, inp).stdout_preview or "")


def test_timeout_is_enforced(tmp_path):
    make_sut(tmp_path, "import time; time.sleep(30)")
    t = Target("sut", [sys.executable, str(tmp_path / "sut.py"), "{input}"],
               limits=Limits(timeout_s=1))
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    o = run_one(t, inp)
    assert o.timed_out and o.duration_ms < 10_000


def test_signal_is_recorded(tmp_path):
    make_sut(tmp_path, "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")
    t = Target("sut", [sys.executable, str(tmp_path / "sut.py"), "{input}"],
               limits=Limits(timeout_s=10))
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    o = run_one(t, inp)
    assert o.signal == 11


def test_missing_command_is_a_configuration_error(tmp_path):
    import pytest
    t = Target("sut", ["definitely-not-a-real-binary-xyz", "{input}"], limits=Limits(timeout_s=5))
    inp = tmp_path / "in.txt"
    inp.write_text("x")
    with pytest.raises(RuntimeError, match="spreadex doctor"):
        run_one(t, inp)


# ----------------------------------------------------------- stdin-driven SUTs

def test_stdin_mode_pipes_the_input_and_passes_no_path(tmp_path):
    """Plenty of real interpreters read only stdin. Before this they could not
    be tested at all: a path they ignore makes every input look like a hang."""
    from spreadex.exec.runner import Target, run_one

    src = tmp_path / "in.txt"
    src.write_text("hello from stdin\n")
    target = Target(name="t", command=["cat"], input_mode="stdin")
    obs = run_one(target, src)

    assert obs.exit_code == 0 and not obs.timed_out
    assert "hello from stdin" in obs.stdout_preview
    assert target.render(src) == ["cat"], "no path is appended in stdin mode"


def test_stdin_mode_closes_the_stream_so_a_reader_does_not_hang(tmp_path):
    """EOF matters as much as the bytes: a program given input but no
    end-of-stream waits for more and dies on the timeout."""
    from spreadex.exec.runner import Limits, Target, run_one

    src = tmp_path / "in.txt"
    src.write_text("1\n2\n3\n")
    reader = tmp_path / "count.py"
    reader.write_text("import sys\nprint(len(sys.stdin.read().split()))\n")
    target = Target(name="t", command=[sys.executable, str(reader)],
                    input_mode="stdin", limits=Limits(timeout_s=10))
    obs = run_one(target, src)
    assert obs.timed_out is False, "stdin was never closed"
    assert obs.stdout_preview.strip() == "3"


def test_file_mode_does_not_hand_the_sut_the_terminal(tmp_path):
    """A SUT that reads stdin despite being given a path used to block on the
    campaign's own terminal and be recorded as a timeout."""
    from spreadex.exec.runner import Limits, Target, run_one

    src = tmp_path / "in.txt"
    src.write_text("ignored\n")
    greedy = tmp_path / "greedy.py"
    greedy.write_text("import sys\nsys.stdin.read()\nprint('done')\n")
    target = Target(name="t", command=[sys.executable, str(greedy), "{input}"],
                    limits=Limits(timeout_s=10))
    obs = run_one(target, src)
    assert obs.timed_out is False
    assert obs.stdout_preview.strip() == "done"


def test_stdin_mode_still_honours_an_explicit_input_placeholder(tmp_path):
    """Some commands want both: the bytes on stdin and the path as an argument
    (a filename for diagnostics, say)."""
    from spreadex.exec.runner import Target

    src = tmp_path / "in.txt"
    src.write_text("x")
    target = Target(name="t", command=["tool", "--name", "{input}"], input_mode="stdin")
    assert target.render(src) == ["tool", "--name", str(src)]


def test_an_unknown_input_mode_is_refused_with_the_two_that_exist(tmp_path):
    from spreadex.core.config import ConfigError, load_config

    cfg = tmp_path / "spreadex.yaml"
    cfg.write_text('sut:\n  command: ["cat"]\n  input_mode: pipe\n'
                   "generators: []\ncorpus: {path: .}\n")
    with pytest.raises(ConfigError) as exc:
        load_config(cfg)
    assert "'file'" in str(exc.value) and "'stdin'" in str(exc.value)


def test_input_mode_reaches_the_target_from_the_config(tmp_path):
    from spreadex.core.config import load_config

    cfg = tmp_path / "spreadex.yaml"
    cfg.write_text('sut:\n  command: ["cat"]\n  input_mode: stdin\n'
                   "generators: []\ncorpus: {path: .}\n")
    assert load_config(cfg).targets[0].input_mode == "stdin"


# ------------------------------------- the options the wizard's Advanced section sets

def _where_am_i(tmp_path):
    """A SUT that reports its working directory and one environment variable."""
    script = tmp_path / "where.py"
    script.write_text("import os, sys\nprint(os.getcwd())\nprint(os.environ.get('SPREADEX_PROBE', '<unset>'))\n")
    return script


def test_a_relative_working_directory_is_relative_to_the_project_not_to_the_process(tmp_path, monkeypatch):
    """Every other relative path in spreadex.yaml means "relative to the project".
    `cwd` resolved against whatever directory the process happened to start in,
    so the same config ran in different places depending on where `spreadex` was
    launched from -- and the UI server is launched from anywhere."""
    from spreadex.exec.runner import Target, run_one

    project = tmp_path / "project"
    (project / "work").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)               # the process is NOT in the project

    script = _where_am_i(tmp_path)
    src = tmp_path / "in.txt"
    src.write_text("x")
    target = Target.from_config(
        {"name": "t", "command": [sys.executable, str(script), "{input}"], "cwd": "work"},
        base_dir=project)
    obs = run_one(target, src)

    assert obs.stdout_preview.splitlines()[0] == str((project / "work").resolve())


def test_a_missing_working_directory_is_named_not_reported_as_a_missing_command(tmp_path):
    """subprocess raises the SAME FileNotFoundError for a missing command and a
    missing cwd, so the runner reported "command not found: 'python'" for a
    perfectly good command -- sending the user to fix the wrong thing."""
    from spreadex.exec.runner import Target, run_one

    src = tmp_path / "in.txt"
    src.write_text("x")
    target = Target.from_config(
        {"name": "t", "command": [sys.executable, "-c", "pass"], "cwd": "no/such/dir"},
        base_dir=tmp_path)
    with pytest.raises(RuntimeError) as exc:
        run_one(target, src)
    message = str(exc.value)
    assert "working directory" in message and "no/such/dir" in message
    assert "command not found" not in message


def test_environment_values_may_be_numbers_in_the_yaml(tmp_path):
    """`env: {LEVEL: 3}` is what a person types. subprocess wants strings and
    raised a TypeError that surfaced as an unexplained crash."""
    from spreadex.exec.runner import Target, run_one

    script = _where_am_i(tmp_path)
    src = tmp_path / "in.txt"
    src.write_text("x")
    target = Target.from_config(
        {"name": "t", "command": [sys.executable, str(script), "{input}"],
         "env": {"SPREADEX_PROBE": 3}}, base_dir=tmp_path)
    obs = run_one(target, src)
    assert obs.stdout_preview.splitlines()[1] == "3"


def test_the_environment_is_added_to_not_substituted_for_the_parents(tmp_path):
    """A SUT given one extra variable must still find PATH and HOME."""
    from spreadex.exec.runner import Target, run_one

    script = tmp_path / "env.py"
    script.write_text("import os\nprint('PATH' in os.environ, os.environ.get('MINE'))\n")
    src = tmp_path / "in.txt"
    src.write_text("x")
    target = Target.from_config(
        {"name": "t", "command": [sys.executable, str(script), "{input}"], "env": {"MINE": "yes"}},
        base_dir=tmp_path)
    assert run_one(target, src).stdout_preview.strip() == "True yes"
