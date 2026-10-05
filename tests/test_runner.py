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
