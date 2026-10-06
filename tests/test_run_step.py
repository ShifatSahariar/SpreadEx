"""Step 5 (Review & run): what the budget choices mean to the engine, and the page."""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config
from tests.test_sut_step import _node

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/spreadex/api/static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()

TIME = {"genMode": "time", "perGen": 30, "count": 200, "execMode": "time", "execMinutes": 5, "execCount": 500,
        "signal": "cc", "model": "tfidf", "jobs": 4}


def _b(run, n=3, timeout=5):
    return _node(f"api.budgetFromRun({json.dumps(run)},{n},{timeout})")


def _e(run, n=3, timeout=5):
    return _node(f"api.runEstimate({json.dumps(run)},{n},{timeout})")


# ---------------------------------------------------------- budget -> config

def test_equal_time_derives_the_total_instead_of_asking_for_a_second_number():
    out = _b(TIME, n=3)
    assert out["generation"] == {"mode": "time", "per_generator": "30s"}
    assert out["budget"] == {"generation": "90s", "execution": "300s"}      # 30 s x 3, 5 min


def test_equal_count_gives_each_generator_a_ceiling_and_no_time_mode_keys():
    out = _b({**TIME, "genMode": "count", "count": 500}, n=2)
    assert out["generation"] == {"count": 500} and out["budget"]["generation"] == "240s"   # 120 s each


def test_a_number_of_tests_sets_max_inputs_and_a_worst_case_time_cap():
    out = _b({**TIME, "execMode": "count", "execCount": 500}, timeout=5)
    assert out["budget"]["max_inputs"] == 500 and out["budget"]["execution"] == "2500s"   # 500 x 5 s
    small = _b({**TIME, "execMode": "count", "execCount": 3}, timeout=5)
    assert small["budget"]["execution"] == "60s", "never below a minute"
    huge = _b({**TIME, "execMode": "count", "execCount": 10_000_000}, timeout=60)
    assert huge["budget"]["execution"] == "86400s", "capped at 24 hours"


def test_the_entire_corpus_means_no_input_cap_and_a_24_hour_ceiling():
    out = _b({**TIME, "execMode": "corpus"})
    assert "max_inputs" not in out["budget"] and out["budget"]["execution"] == "86400s"


def test_with_no_generators_the_generation_total_is_still_a_valid_positive_figure():
    assert _b(TIME, n=0)["budget"]["generation"] == "30s"


def test_the_state_round_trips_through_the_config_it_wrote():
    for run in (TIME, {**TIME, "genMode": "count", "count": 77}, {**TIME, "execMode": "count", "execCount": 12},
                {**TIME, "execMode": "corpus"}, {**TIME, "perGen": 12.5, "execMinutes": 0.5}):
        cfgd = _b(run)
        back = _node(f"api.runFromConfig({json.dumps({'generation': cfgd['generation'], 'budget': cfgd['budget']})})")
        for k in ("genMode", "perGen", "execMode", "execMinutes", "execCount", "count"):
            if k in ("count",) and run["genMode"] != "count":
                continue
            if k == "execCount" and run["execMode"] != "count":
                continue
            if k == "execMinutes" and run["execMode"] != "time":
                continue
            assert back[k] == run[k], (k, run, back)


def test_legacy_configs_load_into_sensible_state():
    r = _node("api.runFromConfig({generation:{count:150},budget:{generation:'2m',execution:'45s'}})")
    assert r["genMode"] == "count" and r["count"] == 150 and r["execMode"] == "time" and r["execMinutes"] == 0.75
    assert _node("api.runFromConfig({})")["genMode"] == "time"


def test_problems_are_named_in_words():
    assert _node(f"api.runProblems({json.dumps({**TIME, 'perGen': 0})})")
    assert _node(f"api.runProblems({json.dumps({**TIME, 'execMode': 'count', 'execCount': 2.5})})")
    assert _node(f"api.runProblems({json.dumps({**TIME, 'execMinutes': -1})})")
    assert _node(f"api.runProblems({json.dumps(TIME)})") == []


# --------------------------------------------------------------- estimates

def test_a_time_limit_is_exact_and_everything_else_says_up_to():
    e = _e(TIME, n=3)
    assert e["exact"] and e["totalS"] == 90 + 300
    c = _e({**TIME, "execMode": "count", "execCount": 100}, n=3, timeout=5)
    assert not c["exact"] and c["execS"] == 500 and c["totalS"] == 90 + 500
    k = _e({**TIME, "execMode": "corpus"})
    assert k["totalS"] is None and not k["exact"]
    g = _e({**TIME, "genMode": "count"}, n=2)
    assert not g["genExact"] and g["genS"] == 240


def test_no_generators_means_no_generation_time():
    assert _e(TIME, n=0)["genS"] == 0 and _e(TIME, n=0)["genExact"] is True


def test_durations_read_well():
    assert _node("[30,89,90,330,5400,7200].map(api.fmtSeconds)") == ["30 s", "89 s", "1.5 minutes", "5.5 minutes", "1.5 hours", "2 hours"]


# --------------------------------------------- the engine honours what it writes

def _project(tmp_path, cfgd, gens="[]"):
    (tmp_path / "seeds").mkdir(exist_ok=True)
    for i in range(6):
        (tmp_path / "seeds" / f"s{i}").write_text(f"input {i}")
    doc = {"sut": {"command": [sys.executable, "-c", "pass"]}, "oracle": {"type": "crash"},
           "generators": [], "corpus": {"path": "seeds"}, "generation": cfgd["generation"], "budget": cfgd["budget"]}
    (tmp_path / "spreadex.yaml").write_text(yaml.safe_dump(doc))
    return load_config(tmp_path / "spreadex.yaml")


def test_a_number_of_tests_really_stops_after_that_many_executions(tmp_path):
    cfg = _project(tmp_path, _b({**TIME, "execMode": "count", "execCount": 3}, n=0))
    assert cfg.budget.max_inputs == 3
    assert Campaign(cfg, log=lambda *_: None).run().executed == 3


def test_the_entire_corpus_runs_every_input(tmp_path):
    cfg = _project(tmp_path, _b({**TIME, "execMode": "corpus"}, n=0))
    assert cfg.budget.max_inputs is None and Campaign(cfg, log=lambda *_: None).run().executed == 6


def test_a_time_limit_config_loads_with_the_derived_budget(tmp_path):
    cfg = _project(tmp_path, _b(TIME, n=0))
    assert cfg.budget.execution_s == 300 and cfg.budget.max_inputs is None
    assert cfg.raw["generation"] == {"mode": "time", "per_generator": "30s"}


# ----------------------------------------------------------------- the page

def test_the_page_has_the_designed_parts():
    for t in ("Review &amp; run", "Set the budget, review your configuration, and launch the campaign.",
              "Generation budget", "Equal time", "Recommended", "Equal count", "Execution budget", "Time limit",
              "Number of tests", "Entire corpus", "Test ordering", "SpreadEx prioritization", "Ready to run",
              "Campaign summary", "Edit all", "Run campaign", "Your inputs and results stay on this machine."):
        assert t in JS, t
    for step in ("SUT", "Grammar", "Generators", "Strategy", "Budget", "Storage"):
        assert f't: "{step}"' in JS, step


def test_step_five_is_called_review_and_run_everywhere_and_is_red():
    assert 't: "Review & run"' in JS
    assert "Budget & run" not in JS and "Budget &amp; run" not in JS
    assert re.search(r"\.tone-red \{ --tone: #ef4444", CSS)


def test_running_is_blocked_until_ready_and_a_problem_names_its_fix():
    r = JS[JS.index("function readiness"):JS.index("function estimateLines")]
    assert "ready: items.every(i => i.ok)" in r and "S.project?.writable !== false" in r
    assert re.search(r'id="launch" onclick="launch\(\)" \$\{readiness\(\)\.ready \? "" : "disabled"\}', JS)
    launch = JS[JS.index("async function launch"):][:200]
    assert "if (!readiness().ready) return;" in launch


def test_the_privacy_line_does_not_overclaim_when_downloads_are_pending():
    p = JS[JS.index('class="side-card runcard"'):][:700]
    assert "Missing generators are downloaded from PyPI first." in p and "isPending" in p
    assert "All data stays" not in JS


def test_typing_never_re_renders_the_inputs_it_is_typed_into():
    f = JS[JS.index("function runInput"):JS.index("function runSet")]
    assert "stepRun()" not in f and "refreshRunPanels()" in f


def test_every_edit_writes_the_config_so_the_summary_and_the_file_agree():
    assert "function syncRun" in JS
    for fn in ("runInput", "runSet"):
        body = JS[JS.index(f"function {fn}("):]
        body = body[:body.index("\n}\n")] if fn == "runInput" else body[:body.index("\n", 10)]
        assert "syncRun()" in body, fn
    assert "max_inputs" in JS[JS.index("function buildYaml"):JS.index("async function saveConfig")]


def test_the_two_budget_cards_stack_on_a_narrow_screen():
    assert "@media (max-width: 900px) { .rbudgets { grid-template-columns: minmax(0, 1fr); } }" in CSS


# ------------------------------------------------ Campaigns before any run

def _empty():
    return JS[JS.index("function campaignsEmpty"):JS.index("async function renderResults")]


def test_campaigns_with_no_runs_is_a_quiet_history_page_not_a_tour():
    e = _empty()
    for t in ("Campaigns", "No campaigns yet", "Set up a campaign", "re-run", "delete"):
        assert t in e, t
    # onboarding belongs to Home
    for t in ("See a real result first", "What you will see here", "spreadex demo", "Overview", "Corpus"):
        assert t not in e, t
    assert "RESULTS_PREVIEW" not in JS and "resultsEmpty" not in JS


def test_campaigns_reads_the_persisted_history_not_the_config_file():
    r = JS[JS.index("async function renderResults"):][:900]
    assert "await loadRuns()" in r and "campaignsEmpty()" in r and "campaignsList()" in r
    assert "configured" not in r and "configured" not in _empty()


def test_the_demo_walkthrough_lives_on_home():
    h = JS[JS.index("function showDemoHint"):][:900]
    assert "spreadex demo --ui" in h and "copyDemoCommand(this)" in h


def test_the_whole_script_parses():
    """The other tests read app.js as text, so a duplicate declaration (which stops the entire page
    loading) passed all of them once. Parse it for real."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "--check", str(STATIC / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
