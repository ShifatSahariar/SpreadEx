"""Step 3: families, per-generator options, logos, and the honest generator list."""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from spreadex.api import setup
from spreadex.core.config import ConfigError, load_config
from spreadex.core.sources import derive_grammars
from spreadex.generators.manager import load_catalog

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/spreadex/api/static"
JS = (STATIC / "app.js").read_text()
CSS = (STATIC / "app.css").read_text()
CALC = ROOT / "src/spreadex/demo/project/calc.bnf"
FAMILIES = {"probabilistic", "constraint-based", "coverage-guided", "llm-based"}


def _project(tmp_path, extra=""):
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, -c, 'pass']\n"
        f"oracle:\n  type: crash\n{extra}")
    return load_config(tmp_path / "spreadex.yaml")


# ---------------------------------------------------------------- catalog

def test_every_catalog_generator_has_a_known_family():
    cat = load_catalog()
    assert cat
    for g in cat.values():
        assert g.family in FAMILIES, (g.id, g.family)


def test_the_api_lists_real_generators_and_keeps_upcoming_ones_apart(tmp_path):
    from spreadex.core.config import Config
    r = setup.generator_status(Config.unconfigured(tmp_path))
    real = {g["id"] for g in r["generators"]}
    soon = {u["id"] for u in r["upcoming"]}
    assert real == set(load_catalog()) and not (real & soon)
    assert {"clusgram", "nautilus", "dharma", "fuzz4all"} <= soon and "llm" not in soon
    assert all(u["family"] in FAMILIES for u in r["upcoming"])
    assert all(g["family"] in FAMILIES for g in r["generators"])
    assert {f["id"] for f in r["families"]} == FAMILIES


def test_no_generator_is_invented_that_the_tool_cannot_run():
    for name in ("Autogram", "LangFuzz", "External command", "Custom generator"):
        assert name not in JS, name


def test_logo_assets_ship_small_and_transparent_where_they_should():
    from PIL import Image
    for gid in ("fandango", "isla", "fuzzingbook", "clusgram", "nautilus", "dharma", "llm"):
        f = STATIC / "assets" / f"gen-{gid}.png"
        assert f.is_file() and f.stat().st_size < 40_000, gid
        assert Image.open(f).size == (128, 128)
        assert f"gen-{gid}.png" in JS
    assert "static/assets/*" in (ROOT / "pyproject.toml").read_text()


# ---------------------------------------------------------- generator_options

def test_valid_generator_options_load_and_change_the_config_hash(tmp_path):
    base = _project(tmp_path).hash()
    cfg = _project(tmp_path, "generator_options:\n  fandango: {constraints: false}\n")
    assert cfg.generator_options == {"fandango": {"constraints": False}}
    assert cfg.hash() != base
    assert _project(tmp_path, "generator_options: {}\n").hash() == base


@pytest.mark.parametrize("block,needle", [
    ("generator_options: [x]\n", "must map"),
    ("generator_options:\n  fandango: yes\n", "must be a mapping"),
    ("generator_options:\n  fandango: {speed: 9}\n", "not an option"),
    ("generator_options:\n  fandango: {constraints: maybe}\n", "true or false"),
])
def test_bad_generator_options_are_refused_with_a_fix(tmp_path, block, needle):
    with pytest.raises(ConfigError, match=needle):
        _project(tmp_path, block)


def _derive(tmp_path, options):
    shutil.copy(CALC, tmp_path / "calc.bnf")
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/c.fan").write_text("where True")
    cfg = _project(tmp_path, "grammar:\n  source: calc.bnf\nsemantics:\n  native:\n    fandango: spec/c.fan\n" + options)
    return derive_grammars(cfg, ["fandango"], log=lambda *_: None)["fandango"].read_text()


def test_constraints_are_used_by_default_and_switched_off_by_the_option(tmp_path):
    assert "where True" in _derive(tmp_path, "")
    other = tmp_path / "off"
    other.mkdir()
    assert "where True" not in _derive(other, "generator_options:\n  fandango: {constraints: false}\n")


# -------------------------------------------------------------- the page

def test_the_page_has_the_designed_parts():
    for t in ("Choose your input generators", "Input specification from previous step", "Recommended generators",
              "Other generators", "Up to 3 shown", "Generator selection", "Automatic recommendation",
              "Cluster Coverage", "Advanced settings", "Selected generators", "Clear all", "Tips",
              "Back to Inputs", "Continue to Testing strategy"):
        assert t in JS, t


def test_the_filter_offers_every_family_and_applies_to_both_sections():
    for label in ("Probabilistic", "Constraint-based", "Coverage-guided", "LLM-based"):
        assert label in JS
    assert JS.count("inFilter(") >= 4 and 'role="tablist"' in JS


def test_upcoming_generators_can_never_be_selected():
    u = JS[JS.index("function upcomingCard"):JS.index("function setGenFilter")]
    assert "<input" not in u and "onclick" not in u and 'aria-disabled="true"' in u and "Coming soon" in u


def test_only_constraint_capable_generators_get_a_choice_and_it_is_only_saved_when_real():
    m = JS[JS.index("function confirmGenModal"):JS.index("function removeFromModal")]
    assert "g.constraints && nativeFile" in m and "constraints: false" in m
    p = JS[JS.index("function paintGenModal"):JS.index("function genModalKeys")]
    assert "if (g.constraints)" in p and "nothing to set" in p


def test_the_popup_is_a_proper_dialog_with_escape_focus_trap_and_focus_return():
    p = JS[JS.index("function paintGenModal"):]
    assert 'role="dialog" aria-modal="true" aria-labelledby="gm-t"' in p
    k = JS[JS.index("function genModalKeys"):]
    k = k[:k.index("\n}\n")]
    assert '"Escape"' in k and '"Tab"' in k and "e.shiftKey" in k
    assert "openGenModal('${esc(g.id)}', this)" in JS and "openerGen" in JS


def test_versions_show_only_the_number():
    assert "function cleanVersion" in JS
    assert "vFandango" not in JS and "g.version ? \"v\"" not in JS


def test_a_disabled_generator_says_why_and_the_yaml_carries_the_options():
    assert "gwhy" in JS and "genFit(g)" in JS
    y = JS[JS.index("function buildYaml"):JS.index("async function saveConfig")]
    assert "generator_options:" in y
    assert re.search(r"\.gcheck input:disabled \{[^}]*not-allowed", CSS)


def test_the_name_clusgram_is_allowed_but_a_path_into_that_repo_is_not():
    src = ROOT / "src"
    hits = [str(p) for p in src.rglob("*") if p.suffix in (".py", ".js", ".yaml", ".css", ".html")
            and re.search(r"/ClusGram|ClusGram/|RESEARCH/ClusGram", p.read_text(errors="replace"))]
    assert not hits, hits


def test_an_incompatible_generator_cannot_be_ticked_unless_it_is_already_chosen():
    card = JS[JS.index("function genCard"):JS.index("function upcomingCard")]
    assert '${fit.ok || chosen ? "" : "disabled"}' in card


def test_fuzz4all_is_listed_inactive_in_the_llm_family_and_cannot_be_run():
    from spreadex.core.config import Config
    r = setup.generator_status(Config.unconfigured(Path(".")))
    f = next(u for u in r["upcoming"] if u["id"] == "fuzz4all")
    assert f["name"] == "Fuzz4All" and f["family"] == "llm-based"
    assert "fuzz4all" not in {g["id"] for g in r["generators"]}
    assert "LLM generator" not in JS and 'fuzz4all: "gen-llm.png"' in JS
