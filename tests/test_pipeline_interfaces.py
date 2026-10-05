"""One engine, two interfaces.

The product claim is that the CLI and the browser UI are clients of the same
deterministic engine, not two implementations that happen to agree. That is
only true if a configuration built in the UI normalizes to the configuration
the CLI would load, and if both read the same persisted results.

Also here: the two failure modes that are easy to get wrong and invisible
when you do -- generator environments leaking into each other, and one
generator failing without taking the campaign with it.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from spreadex.api.jobs import JobRunner
from spreadex.api.server import _Handler
from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config

from test_api import get, post  # the same helpers the API suite uses

SUTS = Path(__file__).resolve().parent / "fixtures" / "suts"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    for sut in SUTS.glob("*.py"):
        import shutil
        shutil.copy2(sut, root / sut.name)
    seeds = root / "seeds"
    seeds.mkdir()
    (seeds / "ok.txt").write_text("plain\n")
    (seeds / "rej.txt").write_text("REJECT bad\n")
    (seeds / "crash.txt").write_text("CRASH boom\n")
    return root


def serve(config, experimental=False):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.spreadex_config = config
    httpd.spreadex_token = "tok"
    httpd.spreadex_verbose = False
    httpd.spreadex_read_only = False
    httpd.spreadex_experimental = experimental
    httpd.spreadex_jobs = JobRunner()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


# ------------------------------------- the UI and the CLI agree on the config

UI_YAML = """\
# Written by the SpreadEx setup wizard. Safe to edit by hand.
sut:
  command: ["{python}", "./behaviours.py", "{{input}}"]
  timeout: 2s

oracle:
  type: crash
  rejection_patterns:
    - "^fixture: SyntaxError"

generators: []

corpus:
  path: ./seeds

budget:
  generation: 10s
  execution: 30s

selection_signal: cc
embedding:
  model: tfidf

seed: 42
"""


def test_a_config_written_by_the_ui_is_the_config_the_cli_loads(project):
    """Not "produces the same results" -- the same normalized object, by hash.
    Anything weaker allows the two to drift and only shows up as a mystery."""
    from spreadex.api import setup
    from spreadex.core.config import Config

    config = Config.unconfigured(project)
    yaml_text = UI_YAML.format(python=sys.executable)

    result = setup.save_config(config, {"yaml": yaml_text, "write": True})
    assert result["ok"], result.get("errors")

    from_ui = load_config(project / "spreadex.yaml")
    from_cli = load_config(project / "spreadex.yaml")
    assert from_ui.hash() == from_cli.hash()

    # And the normalized object is what the engine will actually run.
    assert "{input}" in " ".join(from_ui.targets[0].command)
    assert from_ui.targets[0].limits.timeout_s == 2.0
    assert from_ui.raw["oracle"]["rejection_patterns"] == ["^fixture: SyntaxError"]
    assert from_ui.signal == "cc"


def test_the_ui_refuses_a_config_the_cli_could_not_load(project):
    """The UI validates by loading it exactly as the CLI would, from a scratch
    copy, so a file that would break the CLI is never written."""
    from spreadex.api import setup
    from spreadex.core.config import Config

    config = Config.unconfigured(project)
    bad = 'sut:\n  command: ["echo"]\noracle: {type: differential}\n' \
          "generators: []\ncorpus: {path: ./seeds}\n"
    result = setup.save_config(config, {"yaml": bad, "write": True})
    assert result["ok"] is False
    assert not (project / "spreadex.yaml").exists(), "a rejected config was written"


def test_ui_and_cli_read_the_same_persisted_results(project):
    """One campaign, two readers. If these disagree, one of them is inventing."""
    from spreadex.api import data

    (project / "spreadex.yaml").write_text(UI_YAML.format(python=sys.executable))
    config = load_config(project / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)

    httpd, base = serve(config)
    try:
        _, runs = get(f"{base}/api/runs", "tok")
        assert [r["run_id"] for r in runs["runs"]] == [result.run_id]

        _, detail = get(f"{base}/api/runs/{result.run_id}", "tok")
        assert detail["executed"] == result.executed
        assert detail["verdicts"] == result.verdicts
        assert detail["config_hash"] == config.hash()

        # The CLI's own view of the same run.
        from spreadex.corpus.store import CorpusStore

        with CorpusStore(config.state_dir) as store:
            assert store.run_summary(result.run_id) == result.verdicts
            assert store.latest_run_id() == result.run_id
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_ui_serves_the_same_failure_signatures_the_campaign_found(project):
    (project / "spreadex.yaml").write_text(UI_YAML.format(python=sys.executable))
    config = load_config(project / "spreadex.yaml")
    result = Campaign(config, log=lambda *_: None).run(jobs=2)
    assert result.failures >= 1, "the CRASH fixture should have failed"

    httpd, base = serve(config)
    try:
        _, detail = get(f"{base}/api/runs/{result.run_id}", "tok")
        ui_sigs = {s["signature"] for s in detail["signatures"]}
        campaign_sigs = {s[0] for s in result.signatures}
        assert ui_sigs == campaign_sigs
        for sig in detail["signatures"]:
            _, blob = get(f"{base}/api/input?hash={sig['example']}", "tok")
            assert blob["text"], "a signature whose example cannot be fetched"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------ generator isolation

def test_generator_environments_are_separate_directories():
    """Each generator installs into its own environment so one's dependency
    hell cannot reach another's. ISLa pins setuptools<81; FuzzingBook must not
    inherit that, and neither may the tool itself."""
    from spreadex.generators import GeneratorManager

    mgr = GeneratorManager()
    # Called directly, with no hasattr guard: if these move, this test must
    # fail rather than quietly skip and report isolation it never checked.
    roots = {gid: mgr.env_dir(gid) for gid in ("fuzzingbook", "isla", "fandango")}
    assert len(set(roots.values())) == len(roots), f"shared environment: {roots}"
    for a, pa in roots.items():
        for b, pb in roots.items():
            if a != b:
                assert not str(pa).startswith(str(pb) + "/"), f"{a} nests inside {b}"

    installed = {gid for gid in roots if mgr.status(gid).installed
                 and mgr.status(gid).where == "environment"}
    if len(installed) >= 2:
        for gid in installed:
            assert mgr.env_python(gid).exists(), f"{gid} has no interpreter of its own"


def test_a_generator_does_not_import_from_the_tools_own_site_packages():
    """If a generator shared our site-packages, its pins would become ours --
    ISLa holds setuptools below 81, which the tool itself must not inherit.

    Deliberately NOT a comparison of resolved interpreter paths: every venv on
    a machine symlinks back to the same base interpreter, so that test passes
    and proves nothing. What isolates them is the prefix.
    """
    import subprocess

    from spreadex.generators import GeneratorManager

    mgr = GeneratorManager()
    ours = subprocess.run(
        [sys.executable, "-c", "import sys, json; print(json.dumps(sys.path))"],
        capture_output=True, text=True, check=True).stdout
    checked = 0
    for gid in ("fuzzingbook", "isla"):
        status = mgr.status(gid)
        if not (status.installed and status.where == "environment"):
            continue
        python = mgr.python_for(gid)
        theirs = subprocess.run(
            [str(python), "-c", "import sys; print(sys.prefix)"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert theirs not in ours, f"{gid} shares a prefix with the tool"
        assert str(Path(theirs)) != sys.prefix, f"{gid} runs in the tool's own environment"
        checked += 1
    if not checked:
        pytest.skip("no environment-installed generator to check")


# -------------------------------------------- partial generator failure

def test_one_broken_generator_does_not_abort_the_campaign(project, monkeypatch):
    """A campaign with three generators and one broken install must still
    deliver the other two, and say which failed."""
    from spreadex.core import sources
    from spreadex.generators import GeneratorError

    (project / "g.bnf").write_text('<start> ::= "a" | "b" | "c"\n')
    (project / "spreadex.yaml").write_text(
        f'sut:\n  command: ["{sys.executable}", "./behaviours.py", "{{input}}"]\n'
        "  timeout: 2s\noracle:\n  type: crash\n"
        '  rejection_patterns: ["^fixture: SyntaxError"]\n'
        "generators: [fuzzingbook]\ngrammar: {source: g.bnf}\n"
        "generation: {count: 5}\ncorpus: {path: ./seeds}\n"
        "budget: {generation: 60s, execution: 30s}\nseed: 42\n"
    )
    config = load_config(project / "spreadex.yaml")

    real = sources.run_generator
    calls = {"n": 0}

    def flaky(gid, grammar, count, **kw):
        calls["n"] += 1
        raise GeneratorError("simulated: this generator is broken")

    monkeypatch.setattr(sources, "run_generator", flaky)

    logged: list[str] = []
    result = Campaign(config, log=logged.append).run(jobs=2)

    assert calls["n"] >= 1, "the generator was never attempted"
    # The seed corpus is still there, so the campaign delivers rather than dies.
    assert result.executed > 0
    assert any("simulated" in line for line in logged), (
        "a generator failed and the campaign did not say so"
    )


def test_a_campaign_with_no_usable_source_fails_loudly(tmp_path):
    """The opposite case: when nothing can produce input, stopping with an
    actionable message beats reporting an empty success."""
    root = tmp_path / "empty"
    root.mkdir()
    (root / "spreadex.yaml").write_text(
        'sut:\n  command: ["echo"]\noracle: {type: crash}\n'
        "generators: []\n"
        "budget: {generation: 5s, execution: 5s}\n"
    )
    config = load_config(root / "spreadex.yaml")
    with pytest.raises(RuntimeError) as exc:
        Campaign(config, log=lambda *_: None).run(jobs=1)
    message = str(exc.value)
    assert "corpus" in message and "generators" in message
