"""The Results workspace page: pure formatting under Node, and what the page does and does not claim."""
import json
import re
from pathlib import Path

import pytest

from tests.test_sut_step import _node

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/spreadex/api/static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()
BLOCK = JS[JS.index("// --------------------------------------------------------------- results\n"):
           JS.index("// ------------------------------------------------------------- bootstrap")]


def _call(fn, *args):
    return _node(f"api.{fn}({','.join(json.dumps(a) for a in args)})")


# ------------------------------------------------------------ formatting

def test_milliseconds_read_naturally():
    out = _node("[41, 999, 1000, 1014, 5000, 10000, 12345, null].map(api.fmtMs)")
    assert out == ["41 ms", "999 ms", "1 s", "1.01 s", "5 s", "10 s", "12.3 s", "—"]


def test_durations_drop_empty_units():
    out = _node("[null, 5, 59, 60, 61, 120, 378].map(api.fmtDur)")
    assert out == ["—", "5s", "59s", "1m", "1m 1s", "2m", "6m 18s"]


def test_percentages_guard_against_dividing_by_nothing():
    assert _call("fmtPct", 1601, 1936) == "82.7%" and _call("fmtPct", 1, 0) == "—"
    assert _call("fmtPct", 1, 3, 0) == "33%"


def test_page_numbers_collapse_the_middle():
    assert _call("pageNumbers", 1, 1) == [1]
    assert _call("pageNumbers", 1, 3) == [1, 2, 3]
    assert _call("pageNumbers", 5, 20) == [1, "…", 4, 5, 6, "…", 20]
    assert _call("pageNumbers", 2, 242) == [1, 2, 3, "…", 242]
    assert _call("pageNumbers", 20, 20) == [1, "…", 19, 20]


# ------------------------------------------------------------ structure

def test_the_five_tabs_exist_in_the_designed_order_and_findings_replaces_failures():
    tabs = JS[JS.index("const RESULT_TABS"):][:700]
    ids = re.findall(r'id: "(\w+)"', tabs)
    assert ids == ["overview", "generators", "budget", "findings", "corpus"]
    for fn in ("tabOverview", "tabGenerators", "tabBudget", "tabFindings", "tabCorpus"):
        assert f"function {fn}(" in JS, fn
    assert '"failures"' not in BLOCK and "Failures</" not in BLOCK


def test_the_header_has_the_designed_parts():
    h = BLOCK[BLOCK.index("function resultsHeader"):BLOCK.index("function toggleRunMenu")]
    for t in ("statusPill(", "Generated", "Valid inputs", "Executed", "Crashes", "Timeouts",
              "Divergences", "Export", "Copy replay command", "Run again", "deleteCampaign(", "canAct()"):
        assert t in h, t
    st = BLOCK[BLOCK.index("const RUN_STATUS"):BLOCK.index("function fmtBytes")]
    for t in ("Completed", "Cancelled", "Interrupted", "Failed", "Running"):
        assert t in st, t
    assert 'role="listbox"' in h and "aria-haspopup" in h


def test_overview_cards_are_the_designed_ones():
    o = BLOCK[BLOCK.index("function tabOverview"):BLOCK.index("function detailsTable")]
    for t in ("Campaign outcome", "Top findings", "Generator contribution", "Execution outcome over time",
              "Campaign details", "Prioritization"):
        assert t in o, t


def test_the_page_only_claims_what_a_run_records():
    """Coverage, mutation score, cost and embedding scatter plots are in the mock-ups but a run does
    not record them, so they must not appear -- not even as placeholders with invented numbers."""
    text = "\n".join(l for l in BLOCK.splitlines() if not l.strip().startswith("//")).replace("MutationObserver", "")
    for banned in ("Mutation", "mutation", "Branch coverage", "Estimated cost", "Embedding space", "Vendi",
                   "Silhouette", "Cliff", "RankSum", "$0.0"):
        assert banned not in text, banned


def test_the_pool_relative_caveat_travels_with_cluster_coverage():
    g = BLOCK[BLOCK.index("function tabGenerators"):BLOCK.index("// ------- Budget")]
    assert "pool-relative" in g.lower() or "relative to the pool" in g
    assert "signal_caveats" in g and "contributed" in g and "Interpret the scores with care" in g
    assert "does not make it the best generator in general" in g, "a recommendation is scoped, never absolute"


def test_takeaways_are_conditional_statements_not_fixed_praise():
    b = BLOCK[BLOCK.index("function tabBudget"):BLOCK.index("// ------- Findings")]
    assert "const take = []" in b and b.count("take.push(") >= 4
    assert "Generation ran over its budget" in b and "The budget ended before the corpus did" in b


def test_findings_explain_their_classification_and_can_be_replayed():
    f = BLOCK[BLOCK.index("// ------- Findings"):BLOCK.index("// ------- Corpus")]
    for t in ("Classification", "Execution output", "Similar inputs", "Replay this input", "stdout is not kept"):
        assert t in f, t
    assert "/replay`, { hash: f.hash }" in f, "replay is a POST with the input's hash"
    assert "A signature is not a bug" in f or "Two findings are not necessarily two bugs" in f


def test_a_replay_that_does_not_reproduce_is_not_called_a_pass():
    f = BLOCK[BLOCK.index("function replayPanel"):BLOCK.index("function findingDetailView")]
    assert "Not reproduced" in f and "flaky" in f and "r.reproduced ? \"good\" : \"warn\"" in f


def test_export_sends_the_token_header_instead_of_a_bare_link():
    e = BLOCK[BLOCK.index("async function downloadExport"):BLOCK.index("const RESULT_TABS")]
    assert '"X-SpreadEx-Token": TOKEN' in e and "/export`" in e and "createObjectURL" in e


def test_corpus_search_is_debounced_and_filters_reset_the_page():
    c = BLOCK[BLOCK.index("function corpusFilter"):BLOCK.index("function pageNumbers") if "function pageNumbers" in BLOCK else BLOCK.index("function tabCorpus")]
    assert "clearTimeout(S.cq)" in c and "setTimeout" in c
    assert "st.offset = 0" in c.split("function corpusSearch")[0], "changing a filter returns to page 1"


# --------------------------------------------------------------- safety

UNTRUSTED = ("f.stderr_first", "f.headline", "f.stderr", "f.input", "i.preview", "s.preview", "g.name", "i.generator",
             "f.generator", "t.name", "e.rule", "e.note", "f.detail", "d.signal")


def test_every_field_that_can_carry_the_system_s_output_is_escaped_where_it_is_printed():
    """A finding's stderr and input come from the system under test, which a fuzzer is feeding hostile
    input. Printing any of them raw is stored XSS. Checked in a real browser too; this keeps it checked."""
    bad = []
    for name in UNTRUSTED:
        # only a bare interpolation PRINTS the value; `${f.stderr ? ...}` merely tests it
        for m in re.finditer(re.escape("${" + name + "}"), BLOCK):
            pre = BLOCK[max(0, m.start() - 6):m.start()]
            if not pre.endswith(("esc(", "slice(")) and "esc(" not in BLOCK[max(0, m.start() - 30):m.start()]:
                bad.append(f"{name} @ {BLOCK[max(0, m.start() - 40):m.start() + 30]!r}")
    assert not bad, bad


def test_code_and_stderr_blocks_escape_every_line():
    c = BLOCK[BLOCK.index("function codeBlock"):BLOCK.index("function copyText")]
    assert "esc(l)" in c
    assert "esc(f.stderr)" in BLOCK


def test_the_whole_workspace_stacks_on_a_narrow_screen():
    narrow = CSS[CSS.index("@media (max-width: 1100px)"):]
    for sel in (".fwork", ".resgrid.corpwork", ".fd-grid", ".reshead", ".outcome"):
        assert sel in narrow, sel
    assert ".tscroll { overflow-x: auto; }" in CSS


# ------------------------------------------------ campaigns list and the live view

def _stage(lines, done=False):
    return _node(f"api.liveStage({json.dumps(lines)},{json.dumps(done)})")


def test_the_stage_follows_the_campaigns_own_log_lines():
    assert _stage([]) == "install"
    assert _stage(["Installing 1 generator(s) before the run (first time only).", "- ISLa"]) == "install"
    assert _stage(["Running: python3 sut.py"]) == "generate"
    assert _stage(["Running: x", "Generating..."]) == "generate"
    assert _stage(["Running: x", "Generating...", "Ranking with signal 'cc'..."]) == "rank"
    assert _stage(["Generating...", "Ranking with signal 'cc'...", "Executing against 1 target(s), budget 60s..."]) == "execute"
    assert _stage(["Executing against 1 target(s)"], done=True) == "finish"


def test_a_later_stage_is_never_walked_back_by_an_earlier_looking_line():
    lines = ["Generating...", "Executing against 2 target(s)", "- something that starts with a dash"]
    assert _stage(lines) == "execute"
    assert _stage(["Executing against 1 target(s)", "Installing late note"]) == "execute"


def test_the_stages_are_in_order_and_select_appears_only_when_a_campaign_selects():
    assert [s[0] for s in _node("api.STAGES")] == ["install", "generate", "rank", "select", "execute", "finish"]
    sel = "  selected by cluster coverage: fandango 0.79, fuzzingbook 0.29 (kept 2 of 3; dropped grammarinator 0.12; 105 inputs to execute)"
    assert _stage(["Generating...", "Ranking with signal 'cc'...", sel]) == "select"
    assert _stage(["Ranking with signal 'cc'...", sel, "Executing against 1 target(s)"]) == "execute"
    assert "select" in [s[0] for s in _node(f"stagesFor({json.dumps([sel])})")]
    assert "select" not in [s[0] for s in _node('stagesFor(["Ranking with signal"])')]


def test_the_results_menu_opens_the_list_unless_a_campaign_is_running():
    g = JS[JS.index("function go(tab)"):][:900]
    assert 'tab === "results" && S.rview !== "live"' in g
    assert 'S.rview = S.live?.active ? "live" : "list"' in g


def test_running_a_campaign_lands_on_it_instead_of_a_list():
    launch = JS[JS.index("async function launch"):]
    launch = launch[:launch.index("\n}\n")]
    assert "startLive();" in launch and "watchJob(" not in launch and 'go("results")' not in launch


def test_a_refreshed_page_returns_to_watching_the_running_campaign():
    boot = JS[JS.index("(async function () {"):]
    # an in-process job, or any run holding the project lock (the CLI, another Workbench)
    assert '"/api/activity"' in boot and '!job.idle && !job.done && job.kind === "run"' in boot
    assert '"/api/active"' in boot and "startLive(act)" in boot
    sl = JS[JS.index("function startLive"):JS.index("async function pollLive")]
    assert 'S.rview = "live"' in sl and "setInterval(pollLive" in sl


def test_finishing_opens_the_campaign_and_a_failure_stays_visible_with_a_way_back():
    p = JS[JS.index("async function pollLive"):JS.index("function paintLive")]
    assert "openCampaign(L.runId)" in p and "L.error" in p and '"/api/active"' in p
    live = JS[JS.index("function liveBody"):]
    assert "The campaign stopped" in live and "Back to Review &amp; run" in live


def test_the_back_arrow_returns_to_the_list_and_a_campaign_row_opens_it():
    assert 'onclick="showCampaigns()" aria-label="Back to campaigns"' in JS
    assert "function showCampaigns" in JS and "function openCampaign" in JS and "function pickRun(id) { openCampaign(id); }" in JS
    row = JS[JS.index("function campaignsList"):JS.index("// ---- live: one background job")]
    for col in ("Campaign", "Status", "Started", "SUT", "Generators", "Executed", "Findings", "Duration"):
        assert f"<th>{col}</th>" in row, col
    assert "esc(r.target" in row and "esc(g)" in row, "names from the run are escaped"


def test_the_live_view_only_counts_down_a_budget_that_is_actually_a_time_budget():
    live = JS[JS.index("function liveBody"):]
    assert "p.exec_budget_s < 3600" in live and "indet" in live
    assert "no fixed time to count down" in live


def test_motion_stops_for_people_who_ask():
    assert "prefers-reduced-motion: reduce) { .pulse, .indet span { animation: none; }" in CSS


def test_the_header_is_two_rows_so_the_title_is_never_squeezed():
    """Six chips beside the title do not fit in a 1200px page; at 1400px the title column fell to
    221px and the status pill wrapped. The chips now take their own row as an even six-column grid."""
    assert re.search(r"\.kpis \{ grid-column: 1 / -1; display: grid; grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)", CSS)
    assert ".reshead { display: grid; grid-template-columns: auto minmax(0, 1fr) auto;" in CSS
    assert "@media (max-width: 900px) { .kpis { grid-template-columns: repeat(3" in CSS


def test_each_header_part_is_pinned_to_its_cell_so_dom_order_cannot_reflow_it():
    assert ".reshead > .ractions { grid-row: 1; grid-column: 3; }" in CSS and ".reshead > .kpis { grid-row: 2; }" in CSS


def test_a_campaign_is_named_by_its_run_id_not_its_position():
    """Deleting an earlier campaign must not rename later ones, so no label comes from list order."""
    assert "Campaign #" not in JS and ".number" not in JS
    assert "function campaignName(id)" in JS and "campaignName(d.run_id)" in JS
