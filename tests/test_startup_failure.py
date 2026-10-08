"""A campaign whose system under test cannot start has failed: non-zero exit, an actionable message,
a run recorded as failed -- never "completed" and never a pile of crash findings.

Per-input outcomes (timeouts, expected rejections, real crashes) are untouched.
"""
import json
import sys

import pytest

from spreadex.core.campaign import Campaign, CampaignStartupError
from spreadex.core.config import load_config
from spreadex.corpus.store import CorpusStore


def _project(tmp_path, command: list, seeds=("1", "2", "3"), extra=""):
    (tmp_path / "seeds").mkdir()
    for i, s in enumerate(seeds):
        (tmp_path / "seeds" / f"s{i}").write_text(s)
    (tmp_path / "spreadex.yaml").write_text(
        f"sut: {{command: {json.dumps(command)}, timeout: 2s}}\noracle: {{type: crash}}\n"
        f"generators: []\ncorpus: {{path: seeds}}\nseed: 1\n{extra}")
    return load_config(tmp_path / "spreadex.yaml")


def _status(cfg):
    with CorpusStore(cfg.state_dir) as store:
        return store.conn.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]


@pytest.mark.parametrize("jobs", [1, 3])
def test_a_missing_program_fails_the_campaign(tmp_path, jobs):
    cfg = _project(tmp_path, ["definitely-not-a-program-xyz", "{input}"])
    with pytest.raises(CampaignStartupError) as e:
        Campaign(cfg, log=lambda *_: None).run(jobs=jobs)
    assert "could not be started" in str(e.value) and "spreadex doctor" in str(e.value)
    assert "definitely-not-a-program-xyz" in str(e.value)
    assert _status(cfg) == "failed"


@pytest.mark.parametrize("jobs", [1, 3])
def test_a_missing_script_is_a_startup_failure_not_three_crashes(tmp_path, jobs):
    """The interpreter starts, but the program it was asked to run is not there."""
    cfg = _project(tmp_path, [sys.executable, "missing_script.py", "{input}"])
    with pytest.raises(CampaignStartupError, match="missing_script.py is not in the project folder"):
        Campaign(cfg, log=lambda *_: None).run(jobs=jobs)
    assert _status(cfg) == "failed"
    with CorpusStore(cfg.state_dir) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM failures").fetchone()[0] == 0, "no findings invented"


def test_a_missing_runtime_fails_the_campaign(tmp_path, monkeypatch):
    import hashlib

    from spreadex import runtimes
    from spreadex.runtimes import Runtime

    monkeypatch.setenv("SPREADEX_CACHE", str(tmp_path / "cache"))
    monkeypatch.setitem(runtimes.CATALOG, "tool", Runtime(
        name="tool", title="Test tool", version="1", url="https://example.invalid/t.jar",
        sha256=hashlib.sha256(b"x").hexdigest(), size=1, filename="t.jar", licence="MIT", java_min=11))
    cfg = _project(tmp_path, [sys.executable, "-c", "pass", "${SPREADEX_RUNTIME_TOOL}", "{input}"])
    with pytest.raises(CampaignStartupError, match="spreadex runtimes install tool"):
        Campaign(cfg, log=lambda *_: None).run()


def test_the_cli_exits_non_zero_with_the_reason(tmp_path, monkeypatch, capsys):
    from spreadex.cli.main import main

    _project(tmp_path, ["definitely-not-a-program-xyz", "{input}"])
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        main(["run"])
    assert e.value.code != 0
    err = capsys.readouterr().err
    assert "could not be started" in err and "Completed" not in err


@pytest.mark.parametrize("jobs", [1, 3])
def test_per_input_outcomes_are_unchanged(tmp_path, jobs):
    """A real crash on the very first input, a rejection and a timeout are findings and verdicts,
    not a startup failure."""
    sut = tmp_path / "sut.py"
    sut.write_text(
        "import sys, time\n"
        "s = open(sys.argv[1]).read()\n"
        "if s == 'crash': raise ValueError('boom')\n"
        "if s == 'reject': print('invalid: no', file=sys.stderr); sys.exit(2)\n"
        "if s == 'hang': time.sleep(30)\n")
    cfg = _project(tmp_path, [sys.executable, str(sut), "{input}"], seeds=("crash", "reject", "hang", "ok"),
                   extra="")
    raw = cfg.raw
    raw["oracle"]["rejection_patterns"] = ["^invalid"]
    (tmp_path / "spreadex.yaml").write_text(json.dumps(raw))
    cfg = load_config(tmp_path / "spreadex.yaml")
    result = Campaign(cfg, log=lambda *_: None).run(jobs=jobs)
    assert result.verdicts == {"crash": 1, "expected_rejection": 1, "timeout": 1, "ok": 1}
    assert _status(cfg) == "finished"


def test_a_genuine_crash_on_the_first_and_only_input_is_a_finding(tmp_path):
    sut = tmp_path / "sut.py"
    sut.write_text("import sys\nraise ValueError('boom: ' + open(sys.argv[1]).read())\n")
    cfg = _project(tmp_path, [sys.executable, str(sut), "{input}"], seeds=("x",))
    result = Campaign(cfg, log=lambda *_: None).run()
    assert result.verdicts == {"crash": 1} and len(result.signatures) == 1
    assert _status(cfg) == "finished"


@pytest.mark.parametrize("message", [
    "ModuleNotFoundError: No module named 'lark'",       # an interpreter under test reporting it
    "Error: Unable to access jarfile thing.jar",          # a generated program printing it
    "Error: Cannot find module 'left-pad'",              # Node-style output of the program
])
@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_a_launcher_like_message_from_the_system_itself_is_not_a_startup_failure(tmp_path, message, stream):
    """The SUT prints launcher wording for this INPUT, and runs normally on an empty one: ordinary
    output, judged like any other, never an aborted campaign."""
    sut = tmp_path / "sut.py"
    sut.write_text(
        "import sys\n"
        "s = open(sys.argv[1]).read()\n"
        f"if s: print({message!r}, file=sys.{stream}); sys.exit(1)\n")
    cfg = _project(tmp_path, [sys.executable, str(sut), "{input}"], seeds=("x",))
    logged = []
    result = Campaign(cfg, log=logged.append).run()
    assert result.executed == 1 and _status(cfg) == "finished"
    assert result.verdicts == {"crash": 1}, "judged by the oracle as usual (exit 1 is a crash here)"
    assert any("treated as the system's own output" in line for line in logged)


def test_a_launcher_failure_that_does_not_depend_on_the_input_is_still_caught(tmp_path):
    """Same wording, but printed for every input including an empty one: the program never ran."""
    sut = tmp_path / "sut.py"
    sut.write_text("import sys\nprint('Error: Unable to access jarfile app.jar', file=sys.stderr); sys.exit(1)\n")
    cfg = _project(tmp_path, [sys.executable, str(sut), "{input}"])
    with pytest.raises(CampaignStartupError, match="Unable to access jarfile"):
        Campaign(cfg, log=lambda *_: None).run()
    assert _status(cfg) == "failed"
