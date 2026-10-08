"""Pinned runtimes: downloaded once, verified byte for byte, reused offline, never used when wrong.

Everything is served from a local HTTP server; nothing here reaches the internet.
"""
import hashlib
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from spreadex import runtimes
from spreadex.runtimes import Runtime, RuntimeUnavailable

PAYLOAD = b"pretend this is a jar\n" * 100


@pytest.fixture
def served(tmp_path):
    """A folder served over HTTP on an ephemeral port."""
    root = tmp_path / "www"
    root.mkdir()
    (root / "tool.jar").write_bytes(PAYLOAD)
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def tool(monkeypatch, served, tmp_path):
    root, base = served
    rt = Runtime(name="tool", title="Test tool", version="1.0", url=f"{base}/tool.jar",
                 sha256=hashlib.sha256(PAYLOAD).hexdigest(), size=len(PAYLOAD),
                 filename="tool-1.0.jar", licence="MIT", java_min=11)
    monkeypatch.setitem(runtimes.CATALOG, "tool", rt)
    monkeypatch.setenv("SPREADEX_CACHE", str(tmp_path / "cache"))
    return rt, root, base


def test_a_download_is_verified_and_cached(tool):
    rt, _, _ = tool
    path = runtimes.ensure("tool", log=lambda *_: None)
    assert path.read_bytes() == PAYLOAD and path == runtimes.path_for(rt)
    assert runtimes.verified("tool") == path


def test_a_cached_runtime_is_reused_offline(tool):
    rt, www, _ = tool
    first = runtimes.ensure("tool", log=lambda *_: None)
    (www / "tool.jar").unlink()                                   # the network copy is gone
    assert runtimes.ensure("tool", log=lambda *_: None, url="http://127.0.0.1:9/unreachable") == first


def test_offline_without_a_cache_says_what_to_do(tool):
    with pytest.raises(RuntimeUnavailable) as e:
        runtimes.ensure("tool", log=lambda *_: None, url="http://127.0.0.1:9/unreachable")
    msg = str(e.value)
    assert "could not download" in msg and "spreadex runtimes install tool" in msg
    assert not list(runtimes.path_for(tool[0]).parent.glob("*")), "no partial file is left behind"


def test_a_download_with_the_wrong_checksum_is_discarded(tool):
    rt, www, _ = tool
    (www / "tool.jar").write_bytes(PAYLOAD + b"tampered")
    with pytest.raises(RuntimeUnavailable, match="does not match its pinned checksum"):
        runtimes.ensure("tool", log=lambda *_: None)
    assert runtimes.verified("tool") is None
    assert not runtimes.path_for(rt).exists() and not list(runtimes.path_for(rt).parent.glob(".download-*"))


def test_a_corrupted_cache_is_replaced_not_used(tool):
    rt, _, _ = tool
    path = runtimes.ensure("tool", log=lambda *_: None)
    path.write_bytes(PAYLOAD[:-10])                                # truncated on disk
    assert runtimes.verified("tool") is None
    logged = []
    assert runtimes.ensure("tool", log=logged.append).read_bytes() == PAYLOAD
    assert any("does not match its checksum" in line for line in logged)


def test_a_command_naming_a_missing_runtime_says_how_to_install_it(tool):
    with pytest.raises(RuntimeUnavailable, match="spreadex runtimes install tool"):
        runtimes.substitute("${SPREADEX_RUNTIME_TOOL}")


def test_a_config_naming_a_runtime_loads_before_it_is_installed_and_runs_after(tool, tmp_path):
    """The reference survives loading; the runner resolves it to the verified cached file."""
    from spreadex.core.config import load_config
    from spreadex.exec.runner import Target, run_one

    project = tmp_path / "p"
    project.mkdir()
    (project / "show.py").write_text("import sys; print(open(sys.argv[1]).read()[:21])")
    (project / "spreadex.yaml").write_text(
        f'sut: {{command: ["{sys.executable}", show.py, "${{SPREADEX_RUNTIME_TOOL}}"]}}\n'
        "oracle: {type: crash}\ngenerators: []\ncorpus: {path: seeds}\n")
    cfg = load_config(project / "spreadex.yaml")
    assert "${SPREADEX_RUNTIME_TOOL}" in cfg.targets[0].command
    sample = tmp_path / "in.txt"
    sample.write_text("x")
    with pytest.raises(RuntimeUnavailable):
        run_one(Target.from_config(cfg.raw["sut"], base_dir=project), sample)
    runtimes.ensure("tool", log=lambda *_: None)
    obs = run_one(Target.from_config(cfg.raw["sut"], base_dir=project), sample)
    assert obs.exit_code == 0 and "pretend this is a jar" in (obs.stdout_preview or "")


def test_doctor_reports_the_runtime_and_java(tool, tmp_path, monkeypatch):
    from spreadex.cli.doctor import FAIL, OK, run_checks
    from spreadex.core.config import load_config

    monkeypatch.setattr(runtimes, "java_major", lambda java="java": 21)
    project = tmp_path / "p"
    project.mkdir()
    (project / "seeds").mkdir()
    (project / "seeds" / "a").write_text("1")
    (project / "spreadex.yaml").write_text(
        'sut: {command: [java, -cp, "${SPREADEX_RUNTIME_TOOL}", Main, "{input}"]}\n'
        "oracle: {type: crash}\ngenerators: []\ncorpus: {path: seeds}\n")
    checks = {c.name: c for c in run_checks(load_config(project / "spreadex.yaml"))}
    assert checks["java for tool"].status == OK
    assert checks["runtime 'tool'"].status == FAIL and "runtimes install tool" in checks["runtime 'tool'"].fix
    runtimes.ensure("tool", log=lambda *_: None)
    checks = {c.name: c for c in run_checks(load_config(project / "spreadex.yaml"))}
    assert checks["runtime 'tool'"].status == OK
    monkeypatch.setattr(runtimes, "java_major", lambda java="java": 8)
    checks = {c.name: c for c in run_checks(load_config(project / "spreadex.yaml"))}
    assert checks["java for tool"].status == FAIL and "needs 11+" in checks["java for tool"].detail


def test_the_rhino_pin_is_the_public_release():
    rt = runtimes.get("rhino")
    assert rt.url.startswith("https://repo1.maven.org/maven2/org/mozilla/rhino-all/1.9.1/")
    assert rt.sha256 == "1cc2b468a51857747dcb29ae533e352a2abc04e81c5aa61e397dc774dd395329"
    assert "Not the patched Rhino snapshot" in rt.note
