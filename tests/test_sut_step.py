"""Step 1 (system under test): the pure command helpers run for real under Node,
and the rest of the form is guarded as static source, like the other UI tests."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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
        "\nconst api={splitCommand,joinCommand,parseEnv,envToText,inferKind,DURATION};"
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
    assert "!d.command.trim() || (was && was.cmd === d.command)" in body


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
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", sut_css.replace("#fff", "")), "hard-coded colour"


def test_css_braces_still_balance():
    assert CSS.count("{") == CSS.count("}")


def test_tabs_and_newlines_separate_arguments_like_spaces():
    assert _node("api.splitCommand('a\\tb\\nc').argv") == ["a", "b", "c"]
