"""The Inputs step: extension support in the engine, grammar import by format,
the bundled grammars, and the analysis numbers the wizard shows."""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from spreadex.api import data, setup
from spreadex.core.config import ConfigError, load_config
from spreadex.exec.inputs import InputFiles

ROOT = Path(__file__).resolve().parents[1]


def _project(tmp_path, extra=""):
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, -c, 'pass']\n"
        f"oracle:\n  type: crash\n{extra}")
    return load_config(tmp_path / "spreadex.yaml")


# ------------------------------------------------------------ extension

@pytest.mark.parametrize("value", [".js", ".sql", ".c++", ".a-b"])
def test_a_plain_extension_is_accepted(tmp_path, value):
    assert _project(tmp_path, f"input_extension: '{value}'\n").input_extension == value


@pytest.mark.parametrize("value", ["js", "..js", ".", ".a b", "./x", ".js/../x", ".averyveryverylongext"])
def test_a_malformed_extension_is_refused_with_advice(tmp_path, value):
    with pytest.raises(ConfigError, match="input_extension"):
        _project(tmp_path, f"input_extension: '{value}'\n")


def test_no_extension_keeps_the_blob_path(tmp_path):
    blob = tmp_path / "abc"
    blob.write_text("x")
    assert InputFiles("").path("abc", blob) == blob


def test_an_extension_links_the_same_bytes_under_the_right_name(tmp_path):
    blob = tmp_path / "abc"
    blob.write_text("1 + 1")
    files = InputFiles(".js")
    p = files.path("abc", blob)
    assert p.name == "abc.js" and p.read_text() == "1 + 1"
    assert files.path("abc", blob) == p      # idempotent, safe to call per target


def test_a_campaign_hands_the_system_a_file_with_the_extension(tmp_path):
    """End to end: the SUT itself reports the suffix it was given."""
    from spreadex.core.campaign import Campaign

    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "a").write_text("one")
    (tmp_path / "check.py").write_text(
        "import sys; sys.exit(0 if sys.argv[1].endswith('.js') else 3)\n")
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, check.py]\n  cwd: .\n"
        "oracle:\n  type: crash\n  expected_exit_codes: [0]\n"
        "generators: []\ncorpus:\n  path: seeds\ninput_extension: '.js'\n"
        "budget: {generation: 5s, execution: 10s}\n")
    result = Campaign(load_config(tmp_path / "spreadex.yaml"), log=lambda *_: None).run()
    assert result.executed == 1 and result.failures == 0


# ------------------------------------------------------ import + bundled

def _config(tmp_path):
    return _project(tmp_path)


def test_an_antlr_grammar_can_be_imported_and_is_validated(tmp_path):
    g4 = "grammar T;\nstart : 'a' B ;\nB : 'b' ;\n"
    res = setup.save_grammar(_config(tmp_path), {"path": "grammars/t.g4", "text": g4})
    assert res["ok"], res
    assert (tmp_path / "grammars" / "t.g4").read_text() == g4


def test_a_broken_antlr_grammar_is_refused_not_saved(tmp_path):
    res = setup.save_grammar(_config(tmp_path), {"path": "grammars/bad.g4", "text": "grammar ;;; ((("})
    assert not res["ok"] and not (tmp_path / "grammars" / "bad.g4").exists()


def test_a_grammar_cannot_be_written_outside_the_project(tmp_path):
    res = setup.save_grammar(_config(tmp_path), {"path": "../evil.bnf", "text": "<a> ::= 'x'"})
    assert not res["ok"]


def test_every_bundled_grammar_parses_cleanly_and_arrives_with_its_text():
    gs = setup.bundled_grammars()["grammars"]
    assert gs
    for g in gs:
        assert g["ok"] and g["rules"] > 0 and g["text"].strip() and g["path"].startswith("grammars/")


def test_the_analysis_reports_production_and_alternative_counts(tmp_path):
    cfg = _config(tmp_path)
    shutil.copy(ROOT / "src/spreadex/demo/project/calc.bnf", tmp_path / "calc.bnf")
    rep = data.grammar_report(cfg, "calc.bnf")
    assert rep["rules"] == 7 and rep["alternatives"] >= rep["rules"]


# ------------------------------------------------------------- the page

STATIC = ROOT / "src/spreadex/api/static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()


def test_the_mockup_copy_and_four_modes_are_present():
    for t in ("Define the input specification", "Input language", "File extension",
              "How should SpreadEx understand your input language?", "SpreadEx grammar",
              "Provide grammar", "Import grammar", "No grammar", "Grammar analysis",
              "Grammar ready!", "Start symbol", "Productions", "Alternatives", "Semantic constraints",
              "Back to System under test", "Continue to Generators", "What are input specifications?",
              "Example grammars", "Supported formats", "Tips"):
        assert t in JS, t


def test_no_registry_is_claimed():
    shown = "\n".join(l for l in JS.splitlines() if not l.strip().startswith("//"))
    assert "registry" not in shown.lower()
    assert "View all grammars" not in JS


def test_the_example_grammars_really_parse():
    """The page shows these as examples of each notation; they must be valid."""
    from spreadex.grammar import diagnose
    from spreadex.api.setup import _parse_for
    block = JS[JS.index("const INP_EXAMPLES"):JS.index("const INP_ART") if "const INP_ART" in JS else None]
    block = JS[JS.index("const INP_EXAMPLES"):JS.index("const INP_FORMATS")]
    found = re.findall(r'file: "([^"]+)", code:\s*\n`(.*?)`', block, re.S)
    assert len(found) == 4
    for name, code in found:
        g = _parse_for(name, code)
        assert g.rules and not diagnose(g).errors, name


def test_extension_is_written_only_when_chosen_and_validated_first():
    assert re.search(r'if \(c\.input_extension\) lines\.push\("", `input_extension: \$\{q\(c\.input_extension\)\}`\)', JS)
    c = JS[JS.index("function commitGrammar"):]
    c = c[:c.index("\n}\n")]
    assert "S.config.input_extension = d.ext || undefined" in c
    assert r"A-Za-z0-9_+-]{1,12}" in c


def test_continue_refuses_a_grammar_with_errors():
    c = JS[JS.index("function commitGrammar"):]
    assert 'severity === "error"' in c[:c.index("\n}\n")]


def test_a_bundled_grammar_does_not_decide_the_extension():
    u = JS[JS.index("async function useBundled"):]
    assert "d.ext" not in u[:u.index("\n}\n")]


def test_switching_mode_drops_a_stale_analysis_and_typing_survives_rerenders():
    m = JS[JS.index("function pickInpMode"):]
    m = m[:m.index("\n}\n")]
    assert "stashInp()" in m and 'if (id === "none") d.analysis = null' in m
    for fn in ("chooseInpLang", "inpExampleTab", "toggleInpDetails"):
        assert "stashInp()" in JS[JS.index(f"function {fn}("):][:200], fn


def test_the_assistant_still_finds_the_corpus_and_the_step_reloads_on_config_change():
    assert 'S.inp?.corpus' in JS and "S.inp = null" in JS


def test_narrow_screens_cannot_be_pushed_wide_by_the_example_code():
    assert re.search(r"\.sut-side \{[^}]*grid-template-columns: minmax\(0, 1fr\)", CSS)
    assert re.search(r"\.side-card, \.ex-code, \.sut-main \{ min-width: 0", CSS)
    assert CSS.count("{") == CSS.count("}")


# --------------------------------------------- language logos, extension, cards

def _langs():
    raw = JS[JS.index("const INP_LANGS = ") + len("const INP_LANGS = "):]
    return json.loads(raw[:raw.index("];\n") + 1])


def test_the_language_list_matches_the_design_and_every_entry_can_draw_a_logo():
    langs = _langs()
    names = [l["t"] for l in langs]
    for n in ("JavaScript", "Python", "Java", "SQL", "Lua", "C", "C++", "Rust", "Go", "Ruby", "PHP", "R",
              "Kotlin", "Swift", "TypeScript", "Scala", "C#", "Haskell", "Dart", "Elixir", "BASIC",
              "Plain text", "JSON", "Other", "Not specified"):
        assert n in names, n
    assert [l["t"] for l in langs[-4:]] == ["Plain text", "JSON", "Other", "Not specified"]
    icons = JS[JS.index("const ICONS = {"):JS.index("const BRANDS")]
    for l in langs:
        assert re.fullmatch(r"[0-9A-Fa-f]{6}", l["hex"]), l["t"]
        assert l.get("d") or l.get("lucide") or l.get("badge"), l["t"]
        if l.get("lucide"):
            assert f"\n  {l['lucide']}: I(" in icons or f"\n  {l['lucide']}: I(" in JS, l["lucide"]


def test_each_language_fills_a_plausible_unique_extension():
    exts = {l["id"]: l["ext"] for l in _langs()}
    assert exts["js"] == ".js" and exts["py"] == ".py" and exts["java"] == ".java" and exts["sql"] == ".sql"
    assert exts["other"] == "" and exts[""] == ""
    real = [e for e in exts.values() if e]
    assert len(real) == len(set(real)), "two languages share an extension"
    assert all(re.fullmatch(r"\.[a-z0-9+_-]{1,12}", e) for e in real)


def test_the_default_language_is_not_specified_and_a_typed_extension_is_never_overwritten():
    assert 'langById("")' in JS
    c = JS[JS.index("function chooseInpLang"):]
    c = c[:c.index("\n}\n")]
    assert "if (!d.extTouched) d.ext = l.ext" in c and "stashInp()" in c


def test_the_dropdown_is_an_accessible_listbox_that_closes_on_escape_and_outside_click():
    for t in ('aria-haspopup="listbox"', 'role="listbox"', 'role="option"', 'aria-expanded', "Escape"):
        assert t in JS, t
    assert 'closest?.(".lang-pick")' in JS


def test_java_and_python_use_the_supplied_artwork_which_ships():
    assert '"/static/assets/sut-jar.png"' in JS and '"/static/assets/sut-script.png"' in JS
    assert (STATIC / "assets/sut-jar.png").is_file() and (STATIC / "assets/sut-script.png").is_file()


def test_the_extension_box_is_warm_code_and_the_grammar_picker_uses_plain_words():
    rule = CSS[CSS.index(".sut input.sut-cmd, .sut input#sut-cwd"):]
    assert "input#inp-ext" in rule[:rule.index("}")]
    assert "Pick a ready-made grammar" in JS and "Choose a bundled grammar" not in JS
    assert "lang-tile big" in JS[JS.index("function inpPanel"):]
