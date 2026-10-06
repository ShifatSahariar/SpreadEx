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
    for t in ("Completed", "Not finished", "Generated", "Valid inputs", "Executed", "Crashes", "Timeouts",
              "Divergences", "Export", "Copy replay command", "Run again"):
        assert t in h, t
    assert 'role="listbox"' in h and "aria-haspopup" in h


def test_overview_cards_are_the_designed_ones():
    o = BLOCK[BLOCK.index("function tabOverview"):BLOCK.index("function detailsTable")]
    for t in ("Campaign outcome", "Top findings", "Generator contribution", "Execution outcome over time",
              "Campaign details", "Prioritization"):
        assert t in o, t


def test_the_page_only_claims_what_a_run_records():
    """Coverage, mutation score, cost and embedding scatter plots are in the mock-ups but a run does
    not record them, so they must not appear -- not even as placeholders with invented numbers."""
    text = "\n".join(l for l in BLOCK.splitlines() if not l.strip().startswith("//"))
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
    e = BLOCK[BLOCK.index("async function exportRun"):BLOCK.index("const RESULT_TABS")]
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
