"""The run lock's contract, exercised with real processes and the real OS lock.

Nothing here mocks the platform: the same tests run on POSIX (flock) and on Windows (msvcrt),
and only a run on that platform says the lock works there.
"""
import json
import subprocess
import sys
import textwrap
import time

import pytest

from spreadex.core.lock import RunInProgress, RunLock, active_run

HOLDER = textwrap.dedent('''
    import sys, time
    from spreadex.core.lock import RunLock
    lock = RunLock(sys.argv[1])
    lock.acquire(origin="cli")
    lock.set_run("held-by-child")
    print("locked", flush=True)
    time.sleep(60)
''')


@pytest.fixture
def holder(tmp_path):
    """Another process holding the project's lock, and how to end it abruptly."""
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(tmp_path)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "locked"
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def test_a_lock_held_by_another_process_blocks_without_waiting(tmp_path, holder):
    start = time.time()
    with pytest.raises(RunInProgress) as e:
        RunLock(tmp_path).acquire()
    assert time.time() - start < 2, "acquisition must not block"
    assert e.value.info["run_id"] == "held-by-child"


def test_active_run_reports_the_holders_metadata(tmp_path, holder):
    info = active_run(tmp_path)
    assert info["run_id"] == "held-by-child" and info["origin"] == "cli"
    assert info["pid"] == holder.pid and info["host"] and info["started_at"]


def test_a_killed_holder_leaves_metadata_that_is_not_authoritative(tmp_path, holder):
    holder.kill()
    holder.wait()
    stale = json.loads((tmp_path / "run.lock").read_text())
    assert stale["run_id"] == "held-by-child", "the dead holder's metadata is still on disk"
    assert active_run(tmp_path) is None, "but nobody holds the lock, so nothing is running"
    lock = RunLock(tmp_path)
    previous = lock.acquire(origin="ui")
    assert previous["run_id"] == "held-by-child", "the next holder is told what was left behind"
    lock.release()


def test_release_frees_the_lock_and_clears_the_metadata(tmp_path):
    lock = RunLock(tmp_path)
    lock.acquire(origin="ui")
    lock.set_run("r1")
    assert active_run(tmp_path)["run_id"] == "r1"
    lock.release()
    assert active_run(tmp_path) is None
    assert (tmp_path / "run.lock").read_text() == ""
    again = RunLock(tmp_path)
    assert again.acquire() is None
    again.release()


def test_a_failing_campaign_still_releases_the_lock(tmp_path):
    from spreadex.core.campaign import Campaign
    from spreadex.core.config import load_config

    (tmp_path / "spreadex.yaml").write_text(
        "sut: {command: [python3, x.py, '{input}']}\noracle: {type: crash}\ngenerators: []\n"
        "corpus: {path: empty}\n")
    (tmp_path / "empty").mkdir()
    cfg = load_config(tmp_path / "spreadex.yaml")
    with pytest.raises(RuntimeError):
        Campaign(cfg, log=lambda *_: None).run()       # no inputs: the campaign fails
    assert active_run(cfg.state_dir) is None
