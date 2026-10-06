"""Step gating and page-load landing, run for real under Node.

The functions are lifted out of app.js by name and evaluated with a tiny stub
of the wizard state, so what is tested is the shipped code.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = (Path(__file__).parent.parent / "src" / "spreadex" / "api" / "static" / "app.js").read_text()


def _slice(start: str, end: str) -> str:
    a = JS.index(start)
    return JS[a:JS.index(end, a)]


def _node(setup: str, expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    code = "\n".join([
        _slice("const STEPS = [", "const S = {"),
        _slice("function initialView", "const VIEW_KEY"),
        _slice("function stepDone", "function renderSteps"),
        "const S = { confirmed: new Set(), verifiedSut: null, config: {} };",
        "const cfg = () => S.config;",
        "const targets = () => { const s = S.config.sut || {}; return s.targets || (s.command ? [s] : []); };",
        setup,
        f"process.stdout.write(JSON.stringify({expr}));",
    ])
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


FULL = """S.config = { sut: { command: ["./p", "{input}"] }, grammar: { source: "g.g4" },
                       generators: ["fandango"], oracle: { type: "crash" } };"""
REACH = "['sut','grammar','generators','strategy','run'].map(stepReachable)"


def test_a_new_project_can_only_reach_the_first_step():
    assert _node("", REACH) == [True, False, False, False, False]


def test_an_untested_command_blocks_every_later_step():
    setup = FULL + "['grammar','generators','strategy'].forEach(x => S.confirmed.add(x));"
    assert _node(setup, REACH) == [True, False, False, False, False]
    assert _node(setup, "firstOpenStep()") == "sut"


def test_a_tested_and_confirmed_project_reaches_everything():
    setup = FULL + "['grammar','generators','strategy'].forEach(x => S.confirmed.add(x)); S.verifiedSut = sutKey(S.config.sut);"
    assert _node(setup, REACH) == [True, True, True, True, True]


def test_changing_the_command_needs_a_new_test_and_closes_the_later_steps():
    setup = (FULL + "['grammar','generators','strategy'].forEach(x => S.confirmed.add(x));"
             "S.verifiedSut = sutKey(S.config.sut); S.config.sut = { command: ['./other', '{input}'] };")
    assert _node(setup, REACH) == [True, False, False, False, False]


def test_steps_open_one_by_one_as_each_is_confirmed():
    setup = FULL + "S.verifiedSut = sutKey(S.config.sut); S.confirmed.add('grammar');"
    assert _node(setup, REACH) == [True, True, True, False, False]
    assert _node(setup, "firstOpenStep()") == "generators"


def test_the_sut_key_is_the_same_for_a_single_command_and_its_targets_form():
    assert _node("", "sutKey({command:['a']}) === sutKey({targets:[{command:['a']}]})") is True
    assert _node("", "sutKey({command:['a']}) === sutKey({command:['a'], input_mode:'stdin'})") is False


LAND = "initialView(P, R, V, stepReachable)"


@pytest.mark.parametrize("project,runs,saved,expected", [
    ({"configured": False}, [], None, {"tab": "setup", "step": "sut"}),
    ({"configured": True}, [], None, {"tab": "setup", "step": "run"}),
    ({"configured": True}, [{"run_id": "r2"}, {"run_id": "r1"}], None,
     {"tab": "results", "rview": "run", "current": "r2"}),
    # a saved view that still makes sense wins over the latest run
    ({"configured": True}, [{"run_id": "r2"}, {"run_id": "r1"}],
     {"tab": "results", "rview": "run", "current": "r1"}, {"tab": "results", "rview": "run", "current": "r1"}),
    # ... but not one pointing at a deleted run
    ({"configured": True}, [{"run_id": "r2"}], {"tab": "results", "rview": "run", "current": "gone"},
     {"tab": "results", "rview": "run", "current": "r2"}),
    # ... nor a setup step that is no longer reachable
    ({"configured": False}, [], {"tab": "setup", "step": "run"}, {"tab": "setup", "step": "sut"}),
])
def test_landing_order(project, runs, saved, expected):
    setup = f"const P = {json.dumps(project)}, R = {json.dumps(runs)}, V = {json.dumps(saved)};"
    assert _node(setup, LAND) == expected
