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
    assert "<input" not in u and "onclick" not in u and 'aria-disabled="true"' in u
    assert "gcheck" not in u, "a coming-soon card must not show a checkbox that looks tickable"


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


# ------------------------------------------------ install later, on the run

class _FakeMgr:
    """Stands in for GeneratorManager: records installs, never touches the network."""
    installed_ids = {"fuzzingbook"}
    log: list = []
    fail = None

    def __init__(self, *a, **k):
        self.catalog = {"fandango": _G("Fandango"), "fuzzingbook": _G("FuzzingBook"), "isla": _G("ISLa")}

    def get(self, gid):
        return self.catalog[gid]

    def status(self, gid):
        return type("S", (), {"installed": gid in self.installed_ids})()

    def install(self, gid, log=print, upgrade=False):
        type(self).log.append(("install", gid))
        if type(self).fail == gid:
            raise RuntimeError(f"no network to fetch {gid}")
        self.installed_ids = type(self).installed_ids = type(self).installed_ids | {gid}


class _G:
    def __init__(self, name):
        self.name = name


def _server(tmp_path, gens):
    from spreadex.api.jobs import JobRunner
    (tmp_path / "seeds").mkdir(exist_ok=True)
    (tmp_path / "seeds" / "a").write_text("x")
    cfg = _project(tmp_path, f"generators: [{', '.join(gens)}]\ncorpus:\n  path: seeds\n"
                             "budget: {generation: 5s, execution: 5s}\n")
    return type("Srv", (), {"spreadex_config": cfg, "spreadex_jobs": JobRunner()})()


def _go(monkeypatch, tmp_path, gens, body, installed=("fuzzingbook",), fail=None):
    from spreadex.core import campaign as camp
    _FakeMgr.installed_ids, _FakeMgr.log, _FakeMgr.fail = set(installed), [], fail
    monkeypatch.setattr(setup, "GeneratorManager", _FakeMgr)

    class _Camp:
        def __init__(self, *a, **k): pass
        def run(self, jobs=1):
            _FakeMgr.log.append(("run",))
            return type("R", (), {"run_id": "r", "executed": 0, "verdicts": {}, "new_signatures": []})()
    monkeypatch.setattr(camp, "Campaign", _Camp)
    srv = _server(tmp_path, gens)
    resp = setup.start_run(srv, body)
    srv.spreadex_jobs._thread.join(10)
    return resp, srv.spreadex_jobs.current


def test_missing_generators_are_installed_before_the_run_when_the_user_agreed(monkeypatch, tmp_path):
    resp, job = _go(monkeypatch, tmp_path, ["fandango", "fuzzingbook", "isla"], {"install_missing": True})
    assert resp["ok"] and resp["installing"] == ["fandango", "isla"]
    assert _FakeMgr.log == [("install", "fandango"), ("install", "isla"), ("run",)]   # installed first, never twice
    assert job.ok and job.result["installed"] == ["fandango", "isla"]


def test_nothing_is_installed_unless_the_request_says_so(monkeypatch, tmp_path):
    resp, job = _go(monkeypatch, tmp_path, ["fandango"], {})
    assert resp["installing"] == [] and ("install", "fandango") not in _FakeMgr.log


def test_a_failed_install_stops_the_run_and_says_why(monkeypatch, tmp_path):
    resp, job = _go(monkeypatch, tmp_path, ["fandango"], {"install_missing": True}, fail="fandango")
    assert job.ok is False and "no network to fetch fandango" in job.error
    assert ("run",) not in _FakeMgr.log


def test_already_installed_generators_are_left_alone(monkeypatch, tmp_path):
    resp, job = _go(monkeypatch, tmp_path, ["fuzzingbook"], {"install_missing": True})
    assert resp["installing"] == [] and _FakeMgr.log == [("run",)]


def test_the_install_recipe_comes_from_the_catalog_not_the_request(monkeypatch, tmp_path):
    resp, job = _go(monkeypatch, tmp_path, ["fandango"], {"install_missing": True, "package": "evil", "install": ["x"]})
    assert _FakeMgr.log[0] == ("install", "fandango")
    import inspect
    assert "body.get(\"package\")" not in inspect.getsource(setup.start_run)


# ------------------------------------------------------------- the page

def test_not_installed_becomes_a_plan_once_selected():
    assert "function isPending" in JS and "Installs when you run" in JS
    t = JS[JS.index("function installTag"):JS.index("function inFilter")]
    assert "isPending(g)" in t and "Not installed" in t and "Installed" in t


def test_choosing_a_not_installed_generator_no_longer_blocks_continue():
    c = JS[JS.index("function commitGenerators"):]
    c = c[:c.index("\n}\n")]
    assert "Not installed:" not in c and 'gotoStep("strategy")' in c


def test_coming_soon_is_its_own_grey_section_apart_from_other_generators():
    p = JS[JS.index("function paintGenerators"):JS.index("function openGenModal")]
    assert 'class="gsec soonsec"' in p and "Coming soon" in p
    other = p[p.index('id="gh-oth"'):p.index('class="gsec soonsec"')]
    assert "upcomingCard" not in other
    assert re.search(r"\.gsec\.soonsec \.gcard\.soon \{[^}]*grayscale\(1\)", CSS)


def test_the_review_screen_names_what_will_be_downloaded_and_run_asks_to_install():
    assert "Installed on first run" in JS and "downloaded from PyPI" in JS
    assert "install_missing: true" in JS
    assert "if (!S.generators)" in JS[JS.index("async function stepRun"):][:300]


# ------------------------------------------------------------ publication info

# Checked against Crossref on 2026-10-06. Pinned so an edit cannot drift from the source silently.
VERIFIED = {"grammarinator": ("A-TEST", 2018), "fandango": ("ISSTA", 2025), "isla": ("ESEC/FSE", 2022)}
VERIFIED_UPCOMING = {"nautilus": ("NDSS", 2019), "fuzz4all": ("ICSE", 2024), "clusgram": ("ICST", 2026)}


def test_every_catalog_generator_says_where_it_was_published_or_what_it_is():
    for g in load_catalog().values():
        r = g.reference
        assert r, g.id
        if "venue" in r:
            assert r["venue"] and isinstance(r["year"], int) and 2000 <= r["year"] <= 2030, g.id
        else:
            assert r.get("kind"), f"{g.id}: no paper, so it must say what it is"
        assert r.get("authors") and r.get("title"), g.id


def test_the_venues_and_years_match_what_was_checked():
    cat = load_catalog()
    for gid, (venue, year) in VERIFIED.items():
        assert (cat[gid].reference["venue"], cat[gid].reference["year"]) == (venue, year), gid
    assert "venue" not in cat["fuzzingbook"].reference, "FuzzingBook is a book; do not invent a year for it"


def test_the_api_carries_the_reference_for_real_and_upcoming_generators(tmp_path):
    from spreadex.core.config import Config
    r = setup.generator_status(Config.unconfigured(tmp_path))
    assert all(g["reference"] for g in r["generators"])
    soon = {u["id"]: u["reference"] for u in r["upcoming"]}
    for gid, (venue, year) in VERIFIED_UPCOMING.items():
        assert (soon[gid]["venue"], soon[gid]["year"]) == (venue, year), gid
    assert "venue" not in soon["dharma"], "Dharma has no paper"


def test_the_card_shows_a_small_grey_reference_with_the_full_citation_as_a_tooltip():
    assert "function refLabel" in JS and "function refTitle" in JS and "function refLine" in JS
    assert JS.count("refLine(") >= 4          # real cards, coming-soon cards, the popup
    assert re.search(r"\.gref \{[^}]*color: var\(--color-muted\)", CSS)
    assert 'title="${esc(refTitle(r))}"' in JS
