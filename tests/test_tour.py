"""The guided demo's script, run for real under Node.

The guide must only observe the Workbench: every beat points at a real element, every event it
waits for is one the real handlers emit, and nothing in it clicks for the user.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = (Path(__file__).parent.parent / "src" / "spreadex" / "api" / "static" / "app.js").read_text()
START, END = "// ---- tour (pure", "// ---- end tour"
REGION = JS[JS.index(START):JS.index(END)]
ENGINE = JS[JS.index(END):JS.index("// ------------------------------------------------------------- bootstrap")]


def _node(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", REGION + f"\nprocess.stdout.write(JSON.stringify({expr}));"],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _walk(events):
    return _node("(() => { let id = TOUR[0].id; const seen = [id];"
                 f" for (const e of {json.dumps(events)}) {{ id = tourNext(id, e); seen.push(id); }} return seen; }})()")


HAPPY = ["ack", "probe.ok", "step.sut", "ack", "ack", "step.grammar", "ack", "ack", "step.generators",
         "ack", "ack", "step.strategy", "ack", "ack", "ack", "campaign.started", "stage.generate", "stage.rank",
         "stage.select", "stage.execute", "campaign.done", "ack", "tab.findings", "finding.opened", "ack", "ack", "ack",
         "replay.done", "tab.generators", "ack", "tab.budget", "ack", "tab.corpus", "ack"]


def test_the_whole_happy_path_reaches_the_end_one_beat_at_a_time():
    seen = _walk(HAPPY)
    assert seen[-1] == "done"
    ids = _node("TOUR_IDS")
    expected = [i for i in ids if i not in ("live.install", "live.failed")]
    assert [s for s in seen if s != "live.install"] == expected


def test_unrelated_events_change_nothing():
    for beat, e in [("sut.test", "tab.corpus"), ("sut.test", "nonsense"), ("res.findtab", "step.strategy"),
                    ("res.findtab", "ack"), ("fd.replay", "step.sut"), ("fd.replay", "ack"), ("run.launch", "stage.execute")]:
        assert _node(f'tourNext("{beat}", "{e}")') == beat, (beat, e)


def test_a_failed_probe_keeps_the_user_on_test_connection():
    assert _node('tourNext("sut.test", "probe.fail")') == "sut.test"
    assert _node('tourNext("sut.test", "ack")') == "sut.test", "there is no Next in place of a real action"


def test_doing_the_real_thing_early_moves_on():
    assert _node('tourNext("sut.command", "probe.ok")') == "sut.continue"


def test_a_failed_campaign_shows_the_failure_and_stays():
    assert _node('tourNext("live.execute", "campaign.failed")') == "live.failed"
    assert _node('tourNext("live.failed", "campaign.done")') == "live.failed"
    assert _node('tourNext("live.install", "campaign.done")') == "res.overview"


def test_every_target_is_a_real_element_and_every_event_is_emitted():
    targets = set(re.findall(r'target: "([\w-]+)"', REGION))
    for t in targets:
        assert f'data-tour="{t}"' in JS or f'tour: "{t}"' in JS or ('data-tour="tab-${t.id}"' in JS and t.startswith("tab-")) \
            or ('data-tour="strat-${c.id}"' in JS and t.startswith("strat-")), t
    events = set(re.findall(r'event: "([\w.]+)"', REGION))
    emitted = set(re.findall(r'tourEvent\("([\w.]+)"', JS))
    emitted |= set(re.findall(r'tourEvent\([^)]*\? "([\w.]+)" : "([\w.]+)"', JS)[0])
    dynamic = {"tab.", "stage."}
    for e in events:
        assert e in emitted or any(e.startswith(d) for d in dynamic), e
    assert 'tourEvent("tab." + id)' in JS and 'tourEvent("stage." + st)' in JS and 'st !== L.tourStage' in JS


def test_the_guide_never_clicks_for_the_user():
    code = REGION + ENGINE
    assert ".click()" not in code and "dispatchEvent" not in code
    for fn in ("launch()", "verifyCommand()", "replayFinding()", "commitSut()", "commitGrammar()"):
        assert fn not in code, fn


def test_numbers_in_the_results_beats_come_from_the_run():
    text = _node('TOUR.find(b => b.id === "res.overview").text({ detail: { executed: 117, verdicts: { ok: 84, expected_rejection: 20 }, findings: [{}] } })')
    assert "{{117 inputs}}" in text and "**1 finding**" in text and "{{84}} normal" in text and "{{20}} expected rejections" in text
    budget = _node('TOUR.find(b => b.id === "bud.curve").text({ detail: { executed: 100, findings: [{ position: 22 }, { position: 60 }] } })')
    assert "{{input 23 of 100}}" in budget and "{{23%}} of the inputs that ran" in budget
    assert "decides whether a bug is found" not in budget, "no claim stronger than the data"


def test_back_goes_one_beat_back_but_never_into_the_finished_campaign():
    assert _node('tourPrev("sut.command")') == "sut.command"
    assert _node('tourPrev("sut.test")') == "sut.command"
    assert _node('tourPrev("fd.class")') == "fd.input"
    assert _node('tourPrev("res.overview")') == "run.launch"
    assert _node('tourPrev("live.execute")') == "live.execute"
    assert _node('tourPrev("done")') == "done"


def test_results_steps_show_their_position_in_the_chapter():
    first = _node('tourProgress("res.overview")')
    last = _node('tourProgress("cor.input")')
    assert first["n"] == 1 and last["n"] == last["of"] == first["of"]
    assert _node('tourProgress("sut.test")') is None, "setup already says which of five"


def test_only_results_actions_can_be_passed_and_replay_says_it_was_not_run():
    assert _node('["res.findtab","res.finding","fd.replay","res.gentab","res.budtab","res.cortab"].every(tourCanPass)') is True
    assert _node('["sut.test","sut.continue","run.launch","fd.input","res.overview"].some(tourCanPass)') is False
    assert "not run" in _node('TOUR.find(b => b.id === "fd.replay").passed')


def test_a_fast_campaign_is_shown_one_stage_at_a_time():
    def walk(start, event):
        out, cur = [], start
        for _ in range(10):
            step = _node(f'tourStep("{cur}", "{event}")')
            out.append(step["id"]); cur = step["id"]
            if not step["again"]:
                break
        return out
    assert walk("live.install", "campaign.done") == ["live.generate", "live.rank", "live.select", "live.execute", "res.overview"]
    assert walk("live.generate", "stage.execute") == ["live.rank", "live.select", "live.execute"]
    assert walk("live.rank", "campaign.failed") == ["live.failed"]


def test_the_live_view_waits_for_the_stages_before_opening_results():
    assert 'tourEvent("campaign.done"); await tourSettled();' in JS
    assert "TOUR_DWELL_MS" in ENGINE


def test_explanation_cards_say_next_and_the_page_controls_carry_the_instructions():
    acks = _node("TOUR.filter(b => b.advance.ack && !b.final).map(b => b.advance.ack)")
    assert acks and set(acks) == {"Next"}
    texts = _node('TOUR.filter(b => b.advance.event).map(b => b.text({ detail: { findings: [{}] } }))')
    assert not any(t.startswith("Press ") or " Press " in t for t in texts), "the highlighted control is the instruction"


def test_coach_markup_is_escaped_before_it_is_styled():
    eng = ENGINE
    assert "function tourRich(text)" in eng and "return esc(text)\n    .replace(" in eng


def test_step_two_shows_the_grammar_before_what_it_generates():
    g = _node('TOUR.find(b => b.id === "inputs.grammar").grammar({ grammarRules: ["r1", "r2", "r3"], samples: ["1 + 1", "((((1))))", "2 * (3 + 4) - 5", "10 / 4 + 0.5"] })')
    assert g["rules"] == ["r1", "r2"] and len(g["examples"]) == 2
    short = _node("""[tourShortRule('<expr> ::= <term> | <term> " + " <expr> | <term> " - " <expr>'),
                      tourShortRule('<atom> ::= <number> | "-" <atom> | "(" <expr> ")"')]""")
    assert short == ['<expr> ::= <term> | <term> " + " <expr> | …', '<atom> ::= <number> | "(" <expr> ")" | …']
    assert g["examples"][0] == "2 * (3 + 4) - 5", "an input with nesting and an operator shows the grammar best"
    assert "BNF grammar" in _node('TOUR.find(b => b.id === "inputs.grammar").text({})')


def test_emphasis_is_one_system_on_every_card():
    texts = _node('TOUR.map(b => b.text({ detail: { executed: 9, verdicts: {}, findings: [{ position: 1 }] }, samples: [], timeout: "5s", probe: null }))')
    texts += [_node('TOUR.find(b => b.id === "sut.test").success()')]
    joined = "\n".join(texts)
    # the system under test is always named the same way, never as a concept or plain text
    assert "MiniCalc" in joined
    assert all(m.start() >= 2 and joined[m.start() - 2:m.start()] == "[[" for m in re.finditer("MiniCalc", joined))
    for marker in ("**", "[[", "{{"):
        assert joined.count(marker) == joined.count({"**": "**", "[[": "]]", "{{": "}}"}[marker]) or marker == "**"
    assert joined.count("**") % 2 == 0
    eng = ENGINE
    assert 'class="tour-key"' in eng and 'class="tour-name"' in eng and 'class="tour-val"' in eng


def test_a_running_step_with_nothing_running_moves_on_instead_of_waiting():
    eng = ENGINE
    assert "function tourReconcile()" in eng and "S.live?.active" in eng and '"res.overview"' in eng
    assert 'b.chapter === "Running" && tourReconcile()' in eng, "the paint must not sit on 'Waiting for the page'"
    assert "S.booted" in eng


def test_running_steps_always_have_something_real_to_point_at():
    beats = _node('TOUR.filter(b => b.chapter === "Running").map(b => [b.target, !!(b.route && b.route.live)])')
    for target, has_route in beats:
        assert target == "live-stages|live-view", target
        assert has_route, "away from the live view there must be a way back"
    assert 'data-tour="live-view"' in JS, "the live view header exists for every run, the stage bar only for ours"
    assert 'b.target.split("|")' in ENGINE
    assert 'if (L.external && L.progress?.executed) tourEvent("stage.execute");' in JS


def test_the_demo_steps_teach_cc_constraints_budgets_and_ordering():
    ids = _node("TOUR_IDS")
    order = ["inputs.grammar", "inputs.constraint", "inputs.continue", "gen.card", "gen.cc", "gen.continue",
             "run.genbudget", "run.execbudget", "run.ordering", "run.launch", "live.rank", "live.select", "live.execute"]
    assert [i for i in ids if i in order] == order
    ctx = '{ generators: ["fuzzingbook", "fandango", "grammarinator"], count: 40, keep: 1, execution: "60s", rule: "Do not divide by a literal zero." }'
    assert "{{3}}" in _node(f'TOUR.find(b => b.id === "gen.card").text({ctx})') and "{{40}}" in _node(f'TOUR.find(b => b.id === "gen.card").text({ctx})')
    assert "**Cluster Coverage**" in _node(f'TOUR.find(b => b.id === "gen.cc").text({ctx})')
    assert "{{single best}}" in _node(f'TOUR.find(b => b.id === "gen.cc").text({ctx})')
    assert "{{40}}" in _node(f'TOUR.find(b => b.id === "run.genbudget").text({ctx})')
    assert "{{60s}}" in _node(f'TOUR.find(b => b.id === "run.execbudget").text({ctx})')
    # The demo teaches the abstraction: the user states the rule; no generator name, regex or Python.
    assert _node(f'TOUR.find(b => b.id === "inputs.constraint").rule({ctx})') == "Do not divide by a literal zero."
    card = _node(f'TOUR.find(b => b.id === "inputs.constraint").text({ctx})')
    assert "Fandango" not in card and "where" not in card and "re." not in card
    assert _node('TOUR.find(b => b.id === "inputs.constraint").code === undefined') is True


def test_the_selection_step_reports_the_real_choice_from_the_log():
    line = "  selected by cluster coverage: fandango 0.79, fuzzingbook 0.29 (kept 2 of 3; dropped grammarinator 0.12; 105 inputs to execute)"
    text = _node(f'TOUR.find(b => b.id === "live.select").text({{ selectLine: {json.dumps(line)} }})')
    assert "{{fandango 0.79, fuzzingbook 0.29}}" in text and "{{grammarinator 0.12}}" in text and "{{105}}" in text
    assert "no choice was needed" in _node('TOUR.find(b => b.id === "live.select").text({ selectLine: "" })')


def test_zero_expected_rejections_is_explained_not_left_missing():
    d = '{ detail: { executed: 45, verdicts: { ok: 39, crash: 6 }, findings: [{}, {}], selection: { selected: ["fandango"] } }, rule: "Do not divide by a literal zero." }'
    text = _node(f'TOUR.find(b => b.id === "res.overview").text({d})')
    assert "{{0 expected rejections}}" in text and "followed the constraint" in text
    plain = _node('TOUR.find(b => b.id === "res.overview").text({ detail: { executed: 9, verdicts: { expected_rejection: 2 }, findings: [] } })')
    assert "followed the constraint" not in plain
    assert "allowed to reject" in _node('TOUR.find(b => b.id === "strat.rej").text({})')
