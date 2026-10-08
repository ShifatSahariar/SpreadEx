"""A campaign records what it needs to be explained and replayed -- and never a secret."""
import hashlib
import json
import sys
import zipfile

from spreadex import runtimes
from spreadex.core.campaign import Campaign, _grammar_provenance
from spreadex.core.config import load_config
from spreadex.generators.recorded import write
from spreadex.runtimes import Runtime

SECRET = "sk-test-DO-NOT-LEAK-0123456789abcdef"
PAYLOAD = b"runtime bytes\n"


def _runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("SPREADEX_CACHE", str(tmp_path / "cache"))
    rt = Runtime(name="tool", title="Test tool", version="2.0", url="https://example.invalid/tool.jar",
                 sha256=hashlib.sha256(PAYLOAD).hexdigest(), size=len(PAYLOAD), filename="tool.jar",
                 licence="MIT", java_min=11)
    monkeypatch.setitem(runtimes.CATALOG, "tool", rt)
    p = runtimes.path_for(rt)
    p.parent.mkdir(parents=True)
    p.write_bytes(PAYLOAD)
    return rt


def _project(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "show.py").write_text("import sys; open(sys.argv[1]).read()")
    write(project / "rec", "fuzz4all", [b"a\n", b"b\n"], {"model": "gpt-4.1-mini"})
    (project / "spreadex.yaml").write_text(
        f'sut: {{command: ["{sys.executable}", show.py, "${{SPREADEX_RUNTIME_TOOL}}"]}}\n'
        "oracle: {type: crash}\ngenerators: [fuzz4all]\n"
        "generation: {count: 2, fuzz4all: {mode: recorded, corpus: rec}}\nseed: 3\n")
    return project


def test_the_manifest_names_the_pinned_runtime_and_the_replayed_source(tmp_path, monkeypatch):
    rt = _runtime(monkeypatch, tmp_path)
    project = _project(tmp_path)
    result = Campaign(load_config(project / "spreadex.yaml"), log=lambda *_: None).run()
    m = json.loads((result.run_dir / "manifest.json").read_text())
    pinned = m["targets"][0]["runtimes"][0]
    assert pinned == {"name": "tool", "title": "Test tool", "version": "2.0", "url": rt.url,
                      "sha256": rt.sha256, "licence": "MIT", "verified": True}
    assert m["targets"][0]["version"] == "Test tool 2.0"
    st = m["corpus"]["generation_stats"][0]
    assert st["source"] == "recorded" and st["recording"]["provenance"]["model"] == "gpt-4.1-mini"
    assert m["environment"]["python"], "the interpreter and platform are recorded"


def test_each_generators_grammar_is_recorded_with_its_checksum(tmp_path):
    (tmp_path / "g.fan").write_text("<start> ::= 'a'\n")
    (tmp_path / "spreadex.yaml").write_text(
        "sut: {command: [x, '{input}']}\noracle: {type: crash}\ngenerators: [fandango, fuzz4all]\n"
        "grammar: {fandango: g.fan}\ngeneration: {fuzz4all: {mode: recorded, corpus: rec}}\n")
    got = _grammar_provenance(load_config(tmp_path / "spreadex.yaml"))
    assert got == {"fandango": {"path": "g.fan",
                                "sha256": hashlib.sha256(b"<start> ::= 'a'\n").hexdigest()}}


def test_no_secret_from_the_environment_reaches_the_manifest_results_or_export(tmp_path, monkeypatch, capsys):
    from spreadex.cli.main import main

    _runtime(monkeypatch, tmp_path)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SPREADEX_LLM_API_KEY"):
        monkeypatch.setenv(name, SECRET)
    project = _project(tmp_path)
    result = Campaign(load_config(project / "spreadex.yaml"), log=lambda *_: None).run()
    for f in result.run_dir.rglob("*"):
        if f.is_file():
            assert SECRET not in f.read_text(errors="replace"), f
    monkeypatch.chdir(project)
    assert main(["export", "-o", str(tmp_path / "c.zip")]) == 0
    with zipfile.ZipFile(tmp_path / "c.zip") as z:
        for name in z.namelist():
            assert SECRET.encode() not in z.read(name), name
