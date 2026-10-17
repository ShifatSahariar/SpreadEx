"""Live Fuzz4All through SpreadEx: the adapter, and the pinned artifact against a mock endpoint.

The integration tests need the artifact installed (`spreadex generators install fuzz4all`) and
are skipped otherwise. They never contact a real provider: a scripted OpenAI-compatible server
answers every request, and records them, so the tests can check what reached the "provider".
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

from spreadex.generators import GeneratorError, GeneratorManager
from spreadex.generators.adapters import _batch_size_for, generate_fuzz4all

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from mock_openai_server import MockOpenAI  # noqa: E402

KEY = "sk-test-FUZZ4ALL-SECRET-0123456789"


def test_batch_size_divides_the_count():
    assert _batch_size_for(20, 25) == 20
    assert _batch_size_for(100, 25) == 25
    assert _batch_size_for(12, 5) == 4
    assert _batch_size_for(7, 25) == 7


def test_without_documentation_fuzz4all_says_what_to_add(monkeypatch, tmp_path):
    class Ready:
        def status(self, _):
            return type("S", (), {"installed": True, "detail": ""})()
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    ctx = {"documentation": [], "targets": [], "llm": {"provider": "openai", "model": "m"}}
    with pytest.raises(GeneratorError, match="semantics.guidance"):
        generate_fuzz4all(Ready(), None, 4, tmp_path / "o", 1, 60, context=ctx)


def test_without_llm_settings_fuzz4all_says_how_to_add_them(tmp_path):
    class Ready:
        def status(self, _):
            return type("S", (), {"installed": True, "detail": ""})()
    with pytest.raises(GeneratorError, match="need LLM settings"):
        generate_fuzz4all(Ready(), None, 4, tmp_path / "o", 1, 60,
                          context={"documentation": ["x"], "targets": [], "llm": {}})


# ----------------------------------------------------------- the real artifact

def _installed() -> bool:
    try:
        return GeneratorManager().status("fuzz4all").installed
    except Exception:
        return False


needs_artifact = pytest.mark.skipif(not _installed(), reason="Fuzz4All is not installed")


def _campaign(root: Path, mock: MockOpenAI, count: int):
    from spreadex.core.campaign import Campaign
    from spreadex.core.config import load_config
    from spreadex.demo import materialize

    materialize(root)
    y = yaml.safe_load((root / "spreadex.yaml").read_text())
    y.pop("selection", None)
    y.update(generators=["fuzz4all"], generation={"count": count},
             budget={"generation": "10m", "execution": "60s"}, embedding={"model": "tfidf"},
             llm={"provider": "custom", "base_url": mock.base_url, "model": "mock-model",
                  "api_key_env": "MOCK_LLM_KEY"},
             generator_options={"fuzz4all": {"probe_batch": 2, "language_name": "MiniCalc",
                                             "comment_style": "hash"}})
    (root / "spreadex.yaml").write_text(yaml.safe_dump(y, sort_keys=False))
    return Campaign(load_config(root / "spreadex.yaml"), log=lambda *_: None).run()


@needs_artifact
def test_the_upstream_loop_runs_through_spreadex(tmp_path, monkeypatch):
    """Autoprompting, prompt scoring on the SUT, generation in whole batches, validation of every
    candidate, and feedback of a valid program into the next prompt -- all upstream's."""
    monkeypatch.setenv("MOCK_LLM_KEY", KEY)
    with MockOpenAI() as mock:
        result = _campaign(tmp_path / "p", mock, count=12)
    stats = next(s for s in result.generation_stats if s["generator"] == "fuzz4all")
    d = stats["details"]
    gen_requests = [q for q in mock.requests if "auto-prompting" not in json.dumps(q["body"]["messages"][:1])]
    distill = [q for q in mock.requests if q not in gen_requests]

    assert len(distill) == 4                                   # greedy + 3 sampled candidates
    assert d["sut_executions"]["prompt_scoring"] and sum(d["sut_executions"]["prompt_scoring"].values()) == 8
    assert d["settings"]["batch_size"] == 12 and d["generation_batches"] == 1
    assert sum(d["sut_executions"]["validation"].values()) == 12 and d["candidates_written"] == 12
    assert stats["produced"] > 0 and result.executed > 0
    assert all(q["auth"] == f"Bearer {KEY}" for q in mock.requests)
    # Nothing local reaches the provider: no SUT command, no project path.
    sent = json.dumps([q["body"] for q in mock.requests])
    assert "calc.py" not in sent and str(tmp_path) not in sent


@needs_artifact
def test_feedback_reuses_a_valid_program_in_the_next_prompt(tmp_path, monkeypatch):
    """Upstream's update() puts the last valid (SAFE) program of one batch into the next prompt.
    Two batches of 4 make a second prompt to look at."""
    from spreadex.generators import adapters

    monkeypatch.setenv("MOCK_LLM_KEY", KEY)
    monkeypatch.setitem(adapters.FUZZ4ALL_DEFAULTS, "batch_size", 4)
    with MockOpenAI() as mock:
        _campaign(tmp_path / "q", mock, count=8)
    from mock_openai_server import EXPRESSIONS

    prompts = [q["body"]["messages"][-1]["content"] for q in mock.requests
               if "auto-prompting" not in json.dumps(q["body"]["messages"][:1])]
    first, second = prompts[-2:]
    assert not any(e in first for e in EXPRESSIONS)            # the initial prompt has no example
    assert any(e in second for e in EXPRESSIONS)               # the next one carries a valid program
    assert any(s in second for s in ("semantically equivalent", "mutated program", "Please create"))


@needs_artifact
def test_the_key_is_never_persisted_and_temp_dirs_are_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_LLM_KEY", KEY)
    before = set(os.listdir(tempfile.gettempdir()))
    with MockOpenAI() as mock:
        result = _campaign(tmp_path / "p", mock, count=4)
    for path in (tmp_path / "p").rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path
    from spreadex.core.config import load_config
    from spreadex.core.export import build_export
    zip_path = tmp_path / "x.zip"
    build_export(load_config(tmp_path / "p" / "spreadex.yaml"), result.run_id, zip_path)
    assert KEY.encode() not in zip_path.read_bytes()
    left = {n for n in set(os.listdir(tempfile.gettempdir())) - before
            if n.startswith(("spreadex-fuzz4all-", "spreadex-f4a-"))}
    assert not left


@needs_artifact
def test_an_unreachable_endpoint_fails_the_generator_not_the_campaign(tmp_path, monkeypatch):
    from spreadex.core.campaign import Campaign
    from spreadex.core.config import load_config
    from spreadex.demo import materialize

    monkeypatch.setenv("MOCK_LLM_KEY", KEY)
    materialize(tmp_path / "p")
    y = yaml.safe_load((tmp_path / "p" / "spreadex.yaml").read_text())
    y.pop("selection", None)
    y.update(generators=["fuzz4all"], generation={"count": 4}, embedding={"model": "tfidf"},
             budget={"generation": "3m", "execution": "30s"},
             llm={"provider": "custom", "base_url": "http://127.0.0.1:9/v1", "model": "m",
                  "api_key_env": "MOCK_LLM_KEY"},
             generator_options={"fuzz4all": {"probe_batch": 1}})
    (tmp_path / "p" / "spreadex.yaml").write_text(yaml.safe_dump(y, sort_keys=False))
    lines: list[str] = []
    result = Campaign(load_config(tmp_path / "p" / "spreadex.yaml"), log=lines.append).run()
    assert result.executed == 5                                # the 5 seeds still run
    assert any("fuzz4all" in l and "cannot be reached" in l for l in lines)
    assert not any(KEY in l for l in lines)


@needs_artifact
def test_a_live_corpus_is_replayed_byte_for_byte(tmp_path, monkeypatch):
    """Regenerating with an LLM may differ; replaying the recorded corpus may not."""
    from spreadex.cli.main import main
    from spreadex.core.campaign import Campaign
    from spreadex.core.config import load_config

    monkeypatch.setenv("MOCK_LLM_KEY", KEY)
    with MockOpenAI() as mock:
        live = _campaign(tmp_path / "p", mock, count=6)
    project = tmp_path / "p"
    monkeypatch.chdir(project)
    assert main(["record", live.run_id, "fuzz4all", "-o", "rec"]) == 0
    manifest = json.loads((project / "rec" / "manifest.json").read_text())
    assert manifest["provenance"]["generation"]["details"]["llm"]["model"] == "mock-model"
    assert KEY not in json.dumps(manifest)

    def blobs(run_dir):
        return [json.loads(l)["blob"] for l in (run_dir / "inputs.jsonl").read_text().splitlines()
                if json.loads(l)["generator"] == "fuzz4all"]

    y = yaml.safe_load((project / "spreadex.yaml").read_text())
    y["generation"] = {"count": 6, "fuzz4all": {"mode": "recorded", "corpus": "rec"}}
    (project / "spreadex.yaml").write_text(yaml.safe_dump(y, sort_keys=False))
    replay = Campaign(load_config(project / "spreadex.yaml"), log=lambda *_: None).run()
    assert sorted(set(blobs(replay.run_dir))) == sorted(set(blobs(live.run_dir)))
