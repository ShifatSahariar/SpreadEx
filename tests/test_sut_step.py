"""Step 1 (system under test): the pure command helpers run for real under Node,
and the rest of the form is guarded as static source, like the other UI tests."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
STATIC = Path(__file__).parent.parent / "src" / "spreadex" / "api" / "static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()

START = "// ---- command line helpers"
END = "// ---- end command line helpers"


def _helpers() -> str:
    a = JS.index(START)
    return JS[a:JS.index(END, a)]


def _node(expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = _helpers() + (
        "\nconst api={splitCommand,joinCommand,parseEnv,envToText,inferKind,DURATION,semanticLine,strategyOracle,parseExitCodes,cleanPatterns,STRATEGY_PRESETS,durationSeconds,suggestRejection,runFromConfig,runProblems,budgetFromRun,runEstimate,fmtSeconds,fmtMs,fmtDur,fmtPct,pageNumbers,liveStage,STAGES};"
        f"\nprocess.stdout.write(JSON.stringify({expr}));")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_path_with_a_space_survives_quoting():
    assert _node('api.splitCommand(\'java -jar "/My Tools/rhino.jar" {input}\').argv') == \
        ["java", "-jar", "/My Tools/rhino.jar", "{input}"]


def test_join_then_split_is_the_identity():
    argv = ["a b", 'c"d', "e\\f", "", "g"]
    assert _node(f"api.splitCommand(api.joinCommand({json.dumps(argv)})).argv") == argv


def test_an_unclosed_quote_is_reported_not_swallowed():
    assert "never closed" in _node('api.splitCommand(\'tool "abc\').error')


def test_a_windows_path_is_not_mangled():
    assert _node("api.splitCommand('C:\\\\tools\\\\x.exe {input}').argv") == ["C:\\tools\\x.exe", "{input}"]


def test_env_lines_parse_and_a_bad_line_names_its_number():
    assert _node("api.parseEnv('# c\\nA=1\\n\\nU=a=b').env") == {"A": "1", "U": "a=b"}
    assert "line 2" in _node("api.parseEnv('A=1\\nnonsense').error")


def test_kind_inference():
    assert _node("[api.inferKind(['java','-jar','x']),api.inferKind(['/usr/bin/python3','x']),"
                 "api.inferKind(['./p']),api.inferKind(['make'])]") == ["jar", "script", "cli", "other"]


def test_durations():
    assert _node("['5','5s','2m','1.5h','soon',''].map(d=>api.DURATION.test(d))") == \
        [True, True, True, True, False, False]


# ---------------------------------------------------------------- the form

def test_the_four_run_styles_and_the_mockup_copy_are_present():
    for text in ("Connect your system under test", "How do you run your program?", "Executable",
                 "Java / JVM", "Script / Runtime", "Custom command", "Execution command",
                 "will be replaced with each generated test file", "Test connection",
                 "Runs a quick check with a sample input", "Advanced options",
                 "System ready!", "SpreadEx successfully executed a test input.",
                 "View details", "Continue to Inputs", "What happens here?", "Tips"):
        assert text in JS, text


def test_kinds_are_a_radiogroup_with_the_state_exposed():
    assert 'role="radiogroup"' in JS and 'role="radio"' in JS and "aria-checked" in JS


def test_the_example_tabs_cover_the_four_runtimes():
    for t in ("Java (Rhino)", "Python", "Node.js", "Custom"):
        assert f't: "{t}"' in JS or f't: "{t}",' in JS, t


def test_typing_is_stashed_before_every_rerender():
    # A card or tab click re-renders; without this the command box is wiped.
    for fn in ("pickSutKind", "sutExampleTab", "addSutExtra", "dropSutExtra", "toggleProbeDetails"):
        body = JS[JS.index(f"function {fn}("):]
        assert "stashSut()" in body[:400], fn


def test_a_typed_command_is_never_replaced_by_a_template():
    body = JS[JS.index("function pickSutKind"):]
    body = body[:body.index("\n}\n")]
    # A card never writes the command: its example is only the box's placeholder.
    assert "d.command =" not in body and "d.command=" not in body


def test_verification_sends_the_advanced_options_and_not_a_whitespace_split():
    body = JS[JS.index("async function verifyCommand"):]
    body = body[:body.index("function toggleProbeDetails")]
    for key in ("input_mode", "timeout", "body.cwd", "body.env", "body.memory_mb", "command: r.argv"):
        assert key in body, key
    assert "split(/\\s+/)" not in JS[JS.index("// ---- step 1") if "// ---- step 1" in JS
                                      else JS.index("function sutDraft"):]


def test_commit_and_yaml_carry_the_new_keys():
    commit = JS[JS.index("function commitSut"):]
    for k in ("opts.cwd", "opts.env", 'input_mode = "stdin"', "shared.memory_mb"):
        assert k in commit.replace("shared.input_mode", 'input_mode = "stdin"') or k in commit, k
    y = JS[JS.index("function buildYaml"):JS.index("async function saveConfig")]
    for k in ("cwd:", "env:", "input_mode: stdin", "memory_mb:"):
        assert k in y, k


def test_a_single_command_keeps_its_cwd_and_env_through_the_yaml():
    t = JS[JS.index("function targets()"):JS.index("function buildYaml")]
    assert "cwd: s.cwd, env: s.env" in t


def test_stale_draft_is_dropped_when_the_config_is_reloaded():
    assert re.search(r"S\.config = conf\.parsed \|\| \{\};\s*S\.draft = null;", JS)


def test_the_old_step_is_gone():
    for dead in ("TARGET_KINDS", "readTargets", "targetRow(", "Try it once", "pickKind("):
        assert dead not in JS, dead


def test_layout_is_two_columns_that_stack_and_dark_mode_uses_tokens():
    assert re.search(r"\.sut\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 320px", CSS)
    assert "@media (max-width: 1080px) { .sut { grid-template-columns: minmax(0, 1fr); } }" in CSS
    sut_css = CSS[CSS.index("/* Step 1: connect"):CSS.index(".note.good {")]
    for palette in ("#16A34A", "#1687F8", "#9333EA", "#F59E0B", "#64748B"):  # the icon system's tones
        sut_css = sut_css.replace(palette, "")
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", sut_css.replace("#fff", "")), "hard-coded colour"


def test_css_braces_still_balance():
    assert CSS.count("{") == CSS.count("}")


def test_tabs_and_newlines_separate_arguments_like_spaces():
    assert _node("api.splitCommand('a\\tb\\nc').argv") == ["a", "b", "c"]


# ------------------------------------------------------------ icon system

def test_icons_are_vendored_lucide_not_fetched():
    assert "Lucide (ISC)" in JS and "const BRANDS" in JS
    assert not re.search(r"(unpkg|jsdelivr|cdnjs)[^\"']*lucide", (STATIC / "index.html").read_text() + JS)


def test_icons_use_the_two_pixel_round_stroke_and_no_old_default():
    i = JS[JS.index("const I = "):JS.index("//: The brand mark")]
    assert "o.w || 2" in i and "1.8" not in i and 'stroke-linecap="round"' in i


def test_the_status_and_help_glyphs_the_system_names_exist():
    icons = JS[JS.index("const ICONS = {"):JS.index("const BRANDS")]
    for key in ("info", "success", "alert", "error", "info", "help", "bulb", "external", "copy",
                "example", "grid", "terminal", "doc", "sliders", "shield", "playOutline"):
        assert re.search(rf"\n  {key}: I\(", icons), key


def test_run_style_cards_use_tones_and_brand_marks():
    for pair in ('img: "jar", icon: "java", tone: "orange"', 'img: "script", icon: "python", tone: "blue"',
                 'img: "cli", icon: "terminal", tone: "green"', 'img: "other", icon: "grid", tone: "slate"'):
        assert pair in JS, pair
    for hexv in ("#16A34A", "#1687F8", "#9333EA", "#F59E0B", "#64748B"):
        assert hexv in CSS, hexv
    assert re.search(r"\.tile\s*\{[^}]*width: 44px; height: 44px; border-radius: 12px", CSS)


def test_every_icon_the_ui_asks_for_is_defined():
    icons = JS[JS.index("const ICONS = {"):JS.index("const BRANDS")]
    defined = set(re.findall(r"\n  (\w+): I\(", icons))
    used = set(re.findall(r"ICONS\.(\w+)", JS))
    used |= set(re.findall(r'data-icon="(\w+)"', (STATIC / "index.html").read_text()))
    used |= set(re.findall(r'icon: "(\w+)"', JS)) - {"java", "python", "node"}
    assert not used - defined, used - defined


# --------------------------------------------------- stale / missing token

def test_a_401_is_flagged_and_rendered_as_recoverable_not_as_a_raw_error():
    assert "err.unauthorized = r.status === 401" in JS
    card = JS[JS.index("function failureCard"):JS.index("const esc = s =>")]
    assert "e.unauthorized || !TOKEN" in card and "spreadex ui" in card and 'role="alert"' in card


def test_step_failures_go_through_the_shared_card():
    assert "el(\"view\").innerHTML = failureCard(e);" in JS
    assert "holder.innerHTML = failureCard(e)" in JS


def test_the_run_style_artwork_ships_and_is_transparent():
    from PIL import Image
    for k in ("cli", "jar", "script", "other"):
        f = STATIC / "assets" / f"sut-{k}.png"
        assert f.is_file(), f
        im = Image.open(f)
        assert im.mode == "RGBA" and im.size == (128, 128)
        assert im.getchannel("A").getextrema()[0] == 0, "needs a transparent surround to sit on either theme tile"
        assert f"/static/assets/sut-${{k.img}}.png" in JS
    assert "static/assets/*" in (ROOT / "pyproject.toml").read_text()


def test_tiles_are_theme_tinted_rounded_squares_with_a_dark_lift_for_slate():
    assert re.search(r"\.tile\.big \{ width: 56px; height: 56px; border-radius: 16px", CSS)
    assert CSS.count('.tile.big.slate img { filter: brightness(1.6)') == 2   # explicit dark + system dark


# ------------------------------------------------ polish: tick, code, tips, hero

def test_selected_badges_centre_their_tick_with_grid_not_a_baseline_gap():
    assert ".sut-kind.on .sk-ok { display: grid; place-items: center; }" in CSS
    assert ".inp-g.on .inp-ok { display: grid; place-items: center; }" in CSS
    assert re.search(r"\.sk-ok svg \{ display: block;", CSS)


def test_command_fields_are_warm_bolder_code_and_beat_the_global_input_rule():
    assert "--code-fg: #4a3b32" in CSS and "--code-fg: #f0e4d3" in CSS   # light and dark, neither pure
    rule = CSS[CSS.index(".sut input.sut-cmd, .sut input#sut-cwd"):]
    rule = rule[:rule.index("}")]
    assert "font-weight: 500" in rule and "ui-monospace" in rule and "var(--code-fg)" in rule
    for pure in ("#000", "#fff", "#ffffff", "#000000"):
        assert pure not in rule


def test_tips_bulb_glows_amber_and_the_terminal_hero_is_present():
    assert re.search(r"\.h-ico\.amber \{[^}]*#F59E0B[^}]*drop-shadow", CSS)
    assert 'class="h-ico amber"' in JS
    assert "const SUT_ART" in JS and "${SUT_ART}" in JS


# ------------------------------------------- semantic guidance: UI + step 3 rules

FAN = '{"id":"fandango","name":"Fandango","constraints":true}'
ISLA = '{"id":"isla","name":"ISLa","constraints":true}'
GRM = '{"id":"grammarinator","name":"Grammarinator","constraints":false}'


def _line(g, sem, exp="false"):
    return _node(f"api.semanticLine({g},{sem},{exp})")


def test_nothing_is_said_when_no_semantics_were_supplied():
    assert _line(FAN, "{}") is None and _line(FAN, "undefined") is None


def test_native_constraints_are_used_as_written_by_their_own_generator():
    r = _line(FAN, '{"native":{"fandango":"spec/c.fan"}}')
    assert r["tone"] == "ok" and "used as written" in r["text"]


def test_natural_language_is_not_claimed_to_be_consumed():
    r = _line(FAN, '{"guidance":["spec/s.md"]}')
    assert r["tone"] == "muted" and "not consumed directly" in r["text"]
    assert "--experimental" in r["text"]                                   # no assistant -> says how to get it
    assert "experimental assistant" in _line(FAN, '{"guidance":["spec/s.md"]}', "true")["text"]


def test_a_generator_without_constraint_support_runs_from_the_grammar_alone():
    r = _line(GRM, '{"guidance":["spec/s.md"]}')
    assert r["tone"] == "muted" and "runs from the grammar alone" in r["text"]


def test_constraints_written_for_a_different_generator_are_flagged_not_converted():
    # A generator with no constraint support is simply told so, calmly: nothing was done wrong.
    r = _line(GRM, '{"native":{"fandango":"spec/c.fan"}}')
    assert r["tone"] == "muted" and "has no constraint support" in r["text"] and "grammar alone" in r["text"]
    # One that does support constraints, but got only another generator's file, is flagged.
    r2 = _line(FAN, '{"native":{"isla":"spec/c.isla"}}')
    assert r2["tone"] == "warn" and "ISLa-specific" in r2["text"]


def test_structured_constraints_are_labelled_stored_not_interpreted():
    assert "stored but not interpreted" in _line(FAN, '{"structured":"spec/c.yaml"}')["text"]


def test_step_2_has_the_semantic_section_the_design_asked_for():
    for t in ("Semantic guidance", "Natural language", "Recommended", "Write guidance", "Upload document",
              "Advanced", "Structured constraints", "Generator-specific specification",
              "Save guidance", ".pdf", ".docx", "spreadex[docs]"):
        assert t in JS, t
    assert "reserved" in JS and "does not convert it" in JS


def test_no_invented_confidence_number_or_translation_claim():
    shown = "\n".join(l for l in JS.splitlines() if not l.strip().startswith("//"))
    assert "confidence" not in shown.lower()
    assert "automatically convert" not in shown.lower()


def test_the_yaml_carries_the_semantics_block_and_edits_survive_rerender():
    y = JS[JS.index("function buildYaml"):JS.index("async function saveConfig")]
    assert '"semantics:"' in y and "guidance: [" in y and "native:" in y and "structured:" in y
    assert 'if (el("sem-text")) d.sem.text = el("sem-text").value' in JS


def test_step_3_cards_show_the_rule_line_from_the_pure_function():
    g = JS[JS.index("function genCard"):JS.index("function upcomingCard")]
    assert "semanticLine(g, cfg().semantics" in g and "sem-line" in g


def test_a_native_file_does_not_hide_that_written_guidance_goes_unused():
    both = _line(FAN, '{"native":{"fandango":"spec/c.fan"},"guidance":["spec/s.md"]}')
    assert both["tone"] == "ok" and "written guidance is not used" in both["text"]
    assert "guidance" not in _line(FAN, '{"native":{"fandango":"spec/c.fan"}}')["text"]


def test_each_generator_card_says_plainly_what_it_does_with_the_constraint():
    ok = _line(FAN, '{"guidance":["spec/rules.md"],"native":{"fandango":"spec/constraints.fan"}}')
    assert ok["tone"] == "ok" and "Fandango constraints provided (spec/constraints.fan)" in ok["text"]
    rec = _line(FAN, '{"guidance":["spec/rules.md"]}')
    assert "Recommended: provide a Fandango constraints file (.fan)" in rec["text"]
    none = _line(GRM, '{"guidance":["spec/rules.md"]}')
    assert "has no constraint support" in none["text"] and "grammar alone" in none["text"]
