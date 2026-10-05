"""Step 4 (Testing strategy): oracle config validation and the page."""
import json
import re
import sys
from pathlib import Path

import pytest

from spreadex.core.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/spreadex/api/static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()


def _project(tmp_path, oracle_block):
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, -c, 'pass']\noracle:\n  type: crash\n{oracle_block}")
    return load_config(tmp_path / "spreadex.yaml")


# ----------------------------------------------------------- validation

@pytest.mark.parametrize("key", ["rejection_patterns", "crash_patterns"])
def test_a_malformed_regex_is_refused_at_load_not_in_the_middle_of_a_run(tmp_path, key):
    with pytest.raises(ConfigError) as e:
        _project(tmp_path, f'  {key}: ["SyntaxError("]\n')
    msg = str(e.value)
    assert key in msg and "SyntaxError(" in msg and "regular expression" in msg


def test_valid_patterns_still_load(tmp_path):
    cfg = _project(tmp_path, '  rejection_patterns: ["^js: ", "SyntaxError|ParseError"]\n  crash_patterns: ["Segmentation fault"]\n')
    assert cfg.oracle["rejection_patterns"] == ["^js: ", "SyntaxError|ParseError"]


@pytest.mark.parametrize("block,needle", [
    ("  rejection_patterns: SyntaxError\n", "must be a list"),
    ("  crash_patterns: [1, 2]\n", "text"),
    ("  expected_exit_codes: [0, one]\n", "whole numbers"),
    ("  expected_exit_codes: 1\n", "must be a list"),
])
def test_oracle_lists_must_have_the_right_shape(tmp_path, block, needle):
    with pytest.raises(ConfigError, match=needle):
        _project(tmp_path, block)


def test_an_empty_pattern_is_refused_because_it_would_match_everything(tmp_path):
    with pytest.raises(ConfigError, match="empty"):
        _project(tmp_path, '  rejection_patterns: [""]\n')


# --------------------------------------------- the pure switches -> oracle

from tests.test_sut_step import _node  # noqa: E402  (runs the real JS helpers under Node)


def _oracle(base, st, multi=False):
    return _node(f"api.strategyOracle({json.dumps(base)},{json.dumps(st)},{json.dumps(multi)})")


OFF = {"rej": False, "rejPats": [], "codes": "", "sig": False, "sigPats": [], "diff": False}


def test_everything_off_is_just_the_floor_and_removes_stale_keys():
    stale = {"type": "differential", "rejection_patterns": ["x"], "expected_exit_codes": [1], "crash_patterns": ["y"]}
    assert _oracle(stale, OFF) == {"type": "crash"}


def test_each_switch_writes_only_its_own_keys():
    assert _oracle({}, {**OFF, "rej": True, "rejPats": ["Syntax"], "codes": "0, 1"}) == \
        {"type": "crash", "rejection_patterns": ["Syntax"], "expected_exit_codes": [0, 1]}
    assert _oracle({}, {**OFF, "sig": True, "sigPats": ["Segfault"]}) == {"type": "crash", "crash_patterns": ["Segfault"]}


def test_a_switch_that_is_off_hides_its_text_without_deleting_what_was_typed():
    st = {**OFF, "rej": False, "rejPats": ["Syntax"], "codes": "1"}
    assert _oracle({}, st) == {"type": "crash"}


def test_differential_needs_a_second_implementation():
    assert _oracle({}, {**OFF, "diff": True}, multi=False)["type"] == "crash"
    assert _oracle({}, {**OFF, "diff": True}, multi=True)["type"] == "differential"


def test_hand_written_keys_such_as_banners_survive():
    out = _oracle({"banners": ["^Rhino"], "compare_stdout": False}, OFF)
    assert out["banners"] == ["^Rhino"] and out["compare_stdout"] is False


def test_patterns_are_kept_exactly_as_typed_only_blanks_are_dropped():
    out = _oracle({}, {**OFF, "rej": True, "rejPats": ["^js: ", "  ", "", "A  B"]})
    assert out["rejection_patterns"] == ["^js: ", "A  B"], "a significant trailing space must survive"


def test_exit_codes_ignore_junk_and_keep_negatives():
    assert _node("api.parseExitCodes('0, 1  x 2.5 -1')") == [0, 1, -1]
    assert _node("api.parseExitCodes('')") == []


def test_the_presets_are_the_three_in_the_design_and_start_from_the_floor():
    p = _node("Object.keys(api.STRATEGY_PRESETS)")
    assert p == ["parser", "interpreter", "custom"]
    custom = _node("api.STRATEGY_PRESETS.custom.st")
    assert not any([custom["rej"], custom["sig"], custom["diff"]])
    for k in ("parser", "interpreter"):
        st = _node(f"api.STRATEGY_PRESETS.{k}.st")
        assert not st["diff"], "a preset must never ask for a second implementation the project lacks"


# ------------------------------------------------------------- the page

def test_the_page_has_the_designed_parts():
    for t in ("What do you want to detect?", "Use a preset", "Crashes & timeouts",
              "Expected rejections", "Failure signatures", "Differential testing", "Configuration",
              "Set up the selected checks.", "Quick tip", "Presets", "Compiler / Parser", "Interpreter",
              "Selected checks", "Clear all", "Add reference", "Back to Generators", "Continue to Budget"):
        assert t in JS, t


def test_the_floor_cannot_be_turned_off_and_differential_needs_two_targets():
    assert 'floor: true' in JS and "c.floor || dis ? \"disabled\"" in JS
    assert 'c.id === "diff" && !multi' in JS and "targets().length < 2) return" in JS


def test_the_screen_is_read_once_before_a_change_and_never_after():
    """Reading the inputs AFTER changing state copies the old values back over the new state
    (Undo brought the preset's patterns back, and removing a pattern removed the wrong one)."""
    assert "function readStrat" in JS and "function syncStrat" in JS
    for fn in ("stratSet", "stratPreset", "stratUndo", "stratClear", "stratDropPattern", "stratAddPattern", "stratToggleRow"):
        body = JS[JS.index(f"function {fn}("):]
        body = body[:body.index("\n}\n")] if "\n}\n" in body[:900] else body[:900]
        assert "stashStrat()" not in body, f"{fn} must not re-read the screen after changing state"


def test_continue_is_blocked_for_an_enabled_check_with_nothing_in_it():
    c = JS[JS.index("function commitStrategy"):]
    c = c[:c.index("\n}\n")]
    assert "Expected rejections is on but nothing is set up" in c and "Failure signatures is on but has no patterns" in c


def test_pattern_boxes_use_the_warm_code_style_and_the_hint_is_advisory():
    assert 'class="sut-cmd pat-${key}"' in JS and "function patternHint" in JS
    hint = JS[JS.index("function patternHint") - 400:JS.index("function patternHint")]
    assert "Python's engine" in hint and "last word" in hint


def test_the_tip_can_be_dismissed_and_stays_dismissed_for_the_session():
    assert 'spreadex-tip4' in JS and "function stratDismissTip" in JS


def test_the_semantic_tone_classes_do_not_collide_with_the_shared_step_and_card_tones():
    for tone in ("green", "blue", "purple"):
        assert f".tone-{tone} {{" in CSS and CSS.count(f".tone-{tone} {{") == 1


# --------------------------------------------- recommended timeout + suggestions

def test_durations_parse_like_the_server_does():
    out = _node("['5','5s','2m','1.5h',' 10 s ','soon','','-1'].map(d=>api.durationSeconds(d))")
    assert out == [5, 5, 120, 5400, 10, None, None, None]   # '10 s' is accepted by the server too


def _suggest(probe):
    return _node(f"api.suggestRejection({json.dumps(probe)})")


def test_a_rhino_style_refusal_suggests_exit_3_and_the_js_prefix():
    r = _suggest({"ok": True, "exit_code": 3, "timed_out": False, "signal": None, "stdout": "",
                  "stderr": 'js: "test.js", line 1: syntax error\n'})
    assert r["exitCode"] == 3 and r["pattern"] == "^js: " and "syntax error" in r["line"]


def test_a_named_exception_suggests_the_exception_name_escaped_and_anchored():
    r = _suggest({"ok": True, "exit_code": 1, "stderr": "SyntaxError: Unexpected token ;\n", "stdout": ""})
    assert r["pattern"] == "^SyntaxError"
    r2 = _suggest({"ok": True, "exit_code": 2, "stderr": "Traceback (most recent call last):\n", "stdout": ""})
    assert r2["pattern"] == r"^Traceback \(most recent call last\)"


def test_a_suggested_pattern_is_a_valid_regex_that_matches_its_own_line():
    import re as _re
    for line in ('js: "t.js", line 1: syntax error', "SyntaxError: Unexpected token", "error[E0308]: mismatched types",
                 "parse error near ( at 4", "FATAL: bad input"):
        r = _suggest({"ok": True, "exit_code": 1, "stderr": line, "stdout": ""})
        assert _re.search(r["pattern"], line, _re.IGNORECASE | _re.MULTILINE), (line, r["pattern"])


@pytest.mark.parametrize("probe", [
    {"ok": True, "exit_code": 0, "stderr": "", "stdout": "fine"},          # it accepted the input
    {"ok": True, "exit_code": 1, "timed_out": True, "stderr": "x"},         # a hang is not a refusal
    {"ok": True, "exit_code": None, "signal": 11, "stderr": "segv"},        # a signal is never a refusal
    {"ok": False, "error": "not found"},
    None,
])
def test_nothing_is_suggested_when_it_did_not_look_like_a_refusal(probe):
    assert _suggest(probe) is None


def test_a_refusal_with_no_output_still_suggests_the_exit_code_only():
    r = _suggest({"ok": True, "exit_code": 4, "stderr": "", "stdout": ""})
    assert r["exitCode"] == 4 and r["pattern"] == ""


def test_the_timeout_is_editable_here_in_seconds_recommended_badged_and_resettable():
    for s in ("Execution timeout", "seconds", "Recommended", "Reset to recommended"):
        assert s in JS, s
    assert 'RECOMMENDED_TIMEOUT = "5s"' in JS and 'type="number"' in JS
    body = JS[JS.index("function stratSetTimeout"):]
    body = body[:body.index("\n}\n")]
    assert "S.config.sut" in body and "S.draft" in body, "step 1's draft must stay in step with this edit"
    box = JS[JS.index("function stratTimeoutInput"):]
    assert 'raw + "s"' in box[:400], "the box shows seconds; the config stores a duration"


def test_each_setting_states_its_consequence_in_the_design_s_words():
    for s in ("An input with no response in this time is reported as a timeout.",
              "A non-zero exit is considered a crash unless you configure Expected rejections.",
              "Exit codes used when the system intentionally rejects an input.",
              "treated as a normal input rejection rather than a crash",
              "is always reported as a failure",
              "Matched before rejections",
              "so a genuine crash is not hidden by a broad rejection rule"):
        assert s in JS, s


def test_the_classification_order_is_shown_read_only_and_matches_the_engine():
    assert "How SpreadEx classifies a result" in JS and "fixed by SpreadEx" in JS
    order = JS[JS.index("const CLASSIFY_ORDER"):][:1500]
    engine = (ROOT / "src/spreadex/exec/oracle.py").read_text()
    # the page lists the steps in the order CrashOracle.judge performs them
    idx = [engine.index(k) for k in ("obs.timed_out", "obs.signal is not None", "looks_like_crash(",
                                     "obs.exit_code in self.expected_exit_codes", "looks_like_rejection(")]
    assert idx == sorted(idx)
    pos = [order.index(k) for k in ("No answer in time", "Killed by a signal", "failure message",
                                    "expected exit code", "expected rejection message", "Anything else")]
    assert pos == sorted(pos)


def test_the_observer_runs_the_first_target_and_cannot_add_without_the_user_saying_yes():
    o = JS[JS.index("async function stratObserve"):]
    o = o[:o.index("\n}\n")]
    assert '"/api/probe"' in o and "targets()[0]" in o
    acc = JS[JS.index("function stratAcceptSuggestion"):]
    acc = acc[:acc.index("\n}\n")]
    assert "st.rej = true" in acc, "accepting turns the check on"
    assert "!codes.includes(sg.exitCode)" in acc, "an exit code is never added twice"
    assert "!cleanPatterns(st.rejPats).includes(sg.pattern)" in acc, "nor is a pattern"
    assert "onclick=\"stratAcceptSuggestion()\"" in JS and "Yes, add as expected rejection" in JS



# -------------------------------------------------- the configuration panels

def test_each_row_is_a_tinted_panel_with_a_status_pill_and_pencil_chips():
    for s in ('class="spill"', '"Enabled"', '"Disabled"', 'class="srow tc-${c.tone}', "schip edit", "stratOpen("):
        assert s in JS, s
    assert re.search(r"\.srow\.on \{[^}]*linear-gradient\(180deg, color-mix\(in srgb, var\(--rc\)", CSS)
    assert ".sgrid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in CSS
    assert "@media (max-width: 720px) { .sgrid { grid-template-columns: minmax(0, 1fr); }" in CSS


def test_exit_codes_are_removable_tokens_that_never_duplicate():
    assert "function codeTokens" in JS and "stratDropCode(" in JS and "stratAddCode()" in JS
    add = JS[JS.index("function stratAddCode"):]
    add = add[:add.index("\n}\n")]
    assert "Number.isInteger(n)" in add and "!codes.includes(n)" in add and "readStrat()" in add
    assert 'el("exit-codes")' not in JS, "the comma-separated box is gone; tokens are the state"


def test_the_non_zero_exit_choice_is_the_expected_rejections_switch_not_a_separate_setting():
    sel = JS[JS.index("function stratNonZero"):]
    sel = sel[:sel.index("\n}") + 2] if "\n}" in sel else sel
    assert 'stratSet("rej", v === "judged")' in sel
    assert "Treat as crash (default)" in JS and "Judge by expected rejections" in JS


def test_the_two_column_body_stacks_on_a_narrow_screen_and_checks_before_leaving():
    c = JS[JS.index("function commitStrategy"):]
    c = c[:c.index("\n}\n")]
    assert "tsecs === null || tsecs <= 0" in c, "zero is not a timeout"
