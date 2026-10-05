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
