"""What a developer with their own system hits first: paths, rejections, generator versions.

Each test reproduces something a clean install actually did on 2026-10-06 with a small JSON
validator: every input reported as a crash because `python3 validate.py` was not found, then
correct rejections reported as crashes, and generators silently taken from the host PATH.
"""
import sys
from pathlib import Path

import pytest
import yaml

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from spreadex.corpus.store import CorpusStore
from spreadex.exec.observation import Observation
from spreadex.exec.runner import Target, run_one
from spreadex.exec.setup_check import setup_failure

VALIDATOR = '''import json, sys
try:
    json.loads(open(sys.argv[1]).read())
except json.JSONDecodeError as e:
    print(f"invalid: {e}", file=sys.stderr); sys.exit(2)
print("ok")
'''


def _obs(stderr="", exit_code=1):
    return Observation(input_hash="h", sut_id="t", sut_version=None, exit_code=exit_code, signal=None,
                       timed_out=False, duration_ms=1.0, stdout_hash="", stderr_hash="",
                       stdout_preview=None, stderr_preview=stderr or None)


# ------------------------------------------------------------ 1. paths and a broken setup

def test_a_bare_script_name_is_the_projects_file(tmp_path):
    (tmp_path / "validate.py").write_text(VALIDATOR)
    t = Target(name="t", command=["python3", "validate.py", "{input}"], base_dir=tmp_path)
    cmd = t.resolved_command()
    assert cmd[0] == "python3", "the program itself is looked up on PATH, as a shell would"
    assert cmd[1] == str((tmp_path / "validate.py").resolve())
    # options and names that are not files in the project are left alone
    t2 = Target(name="t", command=["python3", "-u", "missing.py", "--mode=x", "{input}"], base_dir=tmp_path)
    assert t2.resolved_command() == ["python3", "-u", "missing.py", "--mode=x", "{input}"]


def test_the_validator_now_runs_from_its_bare_name(tmp_path):
    (tmp_path / "validate.py").write_text(VALIDATOR)
    sample = tmp_path / "s.json"
    sample.write_text("[1]")
    obs = run_one(Target(name="t", command=[sys.executable, "validate.py", "{input}"], base_dir=tmp_path), sample)
    assert obs.exit_code == 0 and setup_failure(obs) is None


@pytest.mark.parametrize("stderr,exit_code", [
    ("python3: can't open file '/tmp/x/validate.py': [Errno 2] No such file or directory", 2),
    ("Error: Could not find or load main class Main", 1),
    ("Error: Unable to access jarfile rhino.jar", 1),
    ("Traceback (most recent call last):\n  File \"x\", line 1\nModuleNotFoundError: No module named 'lark'", 1),
    ("sh: myparser: command not found", 127),
])
def test_a_system_that_did_not_start_is_recognised(stderr, exit_code):
    assert setup_failure(_obs(stderr, exit_code))


@pytest.mark.parametrize("stderr", ["invalid: Expecting value: line 1 column 1 (char 0)",
                                    "calc: SyntaxError: unexpected token",
                                    "Traceback (most recent call last):\nZeroDivisionError: float modulo"])
def test_a_rejection_or_a_real_crash_is_not_a_setup_failure(stderr):
    assert setup_failure(_obs(stderr, 2)) is None


def _project(tmp_path, command):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "validate.py").write_text(VALIDATOR)
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "a.json").write_text("[1, 2]")
    # Messages the oracle's built-in rejection rules do not know -- the case the clean install hit.
    (tmp_path / "seeds" / "b.json").write_text("[1] 2")
    (tmp_path / "seeds" / "c.json").write_text("1 2")
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": command, "timeout": "5s"}, "oracle": {"type": "crash"},
        "generators": [], "corpus": {"path": "seeds"},
        "budget": {"generation": "5s", "execution": "30s"}}))
    return load_config(tmp_path / "spreadex.yaml")


def test_doctor_runs_the_target_once_and_fails_on_a_broken_command(tmp_path):
    from spreadex.cli.doctor import FAIL, OK, run_checks

    cfg = _project(tmp_path, [sys.executable, "nowhere/validate.py", "{input}"])
    runs = [c for c in run_checks(cfg) if c.name.endswith(" runs")]
    assert runs and runs[0].status == FAIL and "not found" in runs[0].detail

    good = _project(tmp_path / "ok", [sys.executable, "validate.py", "{input}"])
    runs = [c for c in run_checks(good) if c.name.endswith(" runs")]
    assert runs[0].status == OK and "ran once" in runs[0].detail


def test_test_connection_reports_a_system_that_did_not_start(tmp_path):
    from spreadex.api import setup
    from spreadex.core.config import Config

    cfg = Config.unconfigured(tmp_path)
    out = setup.probe_target(cfg, {"command": [sys.executable, "nowhere.py", "{input}"]})
    assert out["ok"] is False and out.get("setup") and "did not start" in out["error"]


# ------------------------------------------------------- 2. rejections reported as crashes

def test_a_first_run_names_crashes_that_are_really_rejections(tmp_path, capsys):
    from spreadex.cli.main import _print_result
    from spreadex.core.firstrun import rejection_hints

    cfg = _project(tmp_path, [sys.executable, "validate.py", "{input}"])
    r = Campaign(cfg, log=lambda *_: None).run()
    assert r.verdicts.get("crash") == 2, "no rejection pattern yet: the two invalid files 'crash'"
    with CorpusStore(cfg.state_dir) as store:
        hints = rejection_hints(store, r.run_id)
    assert hints and hints[0]["exit_code"] == 2 and hints[0]["pattern"] == "^invalid"
    _print_result(r, cfg)
    out = capsys.readouterr().out
    assert "look like your system REJECTING input" in out and '"^invalid"' in out

    # With the suggested pattern, the same inputs are expected rejections and nothing is hinted.
    raw = yaml.safe_load((tmp_path / "spreadex.yaml").read_text())
    raw["oracle"]["rejection_patterns"] = [hints[0]["pattern"]]
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump(raw))
    cfg = load_config(tmp_path / "spreadex.yaml")
    r = Campaign(cfg, log=lambda *_: None).run()
    assert r.verdicts.get("expected_rejection") == 2 and not r.verdicts.get("crash")


def test_a_real_crash_is_never_hinted_as_a_rejection(tmp_path):
    from spreadex.core.firstrun import rejection_hints

    (tmp_path / "boom.py").write_text("import sys\nopen(sys.argv[1]).read()\n1 % 0\n")
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "a").write_text("x")
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump({
        "sut": {"command": [sys.executable, "boom.py", "{input}"]}, "oracle": {"type": "crash"},
        "generators": [], "corpus": {"path": "seeds"}, "budget": {"generation": "5s", "execution": "30s"}}))
    cfg = load_config(tmp_path / "spreadex.yaml")
    r = Campaign(cfg, log=lambda *_: None).run()
    with CorpusStore(cfg.state_dir) as store:
        assert r.verdicts.get("crash") == 1 and rejection_hints(store, r.run_id) == []


# --------------------------------------------------- 3. pinned, isolated generator versions

def test_every_catalog_generator_is_pinned_to_an_exact_version():
    from spreadex.generators.manager import GeneratorManager, load_catalog

    for gid, gen in load_catalog().items():
        assert GeneratorManager.pinned_version(gen), f"{gid} is not pinned"


def test_a_generator_on_the_host_path_is_not_used_unless_allowed(tmp_path, monkeypatch):
    from spreadex.generators.manager import GeneratorManager

    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "fandango").write_text("#!/bin/sh\necho 'Fandango 9.9'\n")
    (fake / "fandango").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    isolated = GeneratorManager(cache_dir=tmp_path / "cache", allow_host=False)
    assert not isolated.status("fandango").installed
    assert isolated.executable_for("fandango", "fandango") is None
    host = GeneratorManager(cache_dir=tmp_path / "cache", allow_host=True)
    assert host.status("fandango").installed and host.status("fandango").where == "host"


def test_init_only_asks_for_what_was_not_given(tmp_path, capsys):
    from spreadex.cli.main import main

    main(["init", str(tmp_path / "a"), "--command", "python3", "v.py", "{input}", "--grammar", "g.bnf"])
    out = capsys.readouterr().out
    assert "set sut.command" not in out and "input source" not in out and "1. spreadex doctor" in out
    main(["init", str(tmp_path / "b")])
    out = capsys.readouterr().out
    assert "set sut.command and set an input source" in out
