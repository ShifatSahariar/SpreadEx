import sys

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
