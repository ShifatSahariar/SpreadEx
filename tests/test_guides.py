"""Help & Guides: complete, accurate against the code they describe, safe, and in step with the UI.

The guides are Markdown in static/guides/, rendered by the Workbench. These tests read option names
from the Workbench source and the command reference from the real parser, so a renamed option or
a removed command fails here instead of leaving the guides quietly wrong.
"""
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "spreadex" / "api" / "static"
GUIDES = STATIC / "guides"
JS = (STATIC / "app.js").read_text()
SECTIONS = ["sut", "inputs", "generators", "strategy", "run", "results", "troubleshooting"]
STEPS = SECTIONS[:5]


def md(section: str) -> str:
    return (GUIDES / f"{section}.md").read_text()


def all_md() -> str:
    return "\n".join(md(s) for s in SECTIONS)


def titles(const: str) -> list[str]:
    """The `t:` labels of an array constant in app.js (SUT_KINDS, INP_MODES, ...)."""
    block = JS[JS.index(f"const {const} = "):]
    block = block[:block.index("];") if "];" in block[:4000] else block.index("};")]
    return re.findall(r'\bt: "([^"]+)"', block)


def slug(text: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text.lower())))


def anchors(section: str) -> set[str]:
    return {slug(h) for h in re.findall(r"^#{2,3} (.+)$", md(section), re.M)}


# ------------------------------------------------------------------ structure

def test_the_seven_sections_exist_and_match_the_navigation():
    ids = re.findall(r'\{ id: "([a-z]+)",\s+n: \d', JS[JS.index("const GUIDES = ["):])
    assert ids == SECTIONS
    for s in SECTIONS:
        assert md(s).startswith("# "), s


def test_guides_is_a_top_level_menu_entry():
    html = (STATIC / "index.html").read_text()
    assert 'id="tab-guides"' in html and ">Guides</button>" in html
    nav = html[html.index('<nav class="tabs"'):html.index("</nav>")]
    assert [m for m in re.findall(r">(\w+)</button>", nav)] == ["Home", "Setup", "Campaigns", "Guides"]


@pytest.mark.parametrize("section", STEPS)
def test_every_step_guide_has_the_same_parts(section):
    text = md(section)
    for heading in ("## What this step does", "## Your options", "## When to choose which", "## Examples",
                    "## Common problems"):
        assert heading in text, f"{section}: {heading}"
    tabs = text[text.index(":::tabs"):]
    assert [t for t in re.findall(r"^::tab (.+)$", tabs, re.M)[:3]] == ["MiniCalc", "Rhino", "Your own program"]
    assert text.count(":::problem ") >= 2 and ":::advanced " in text, section
    for block in re.findall(r":::problem .+?\n:::", text, re.S):
        assert "\ncause: " in block and "\nfix: " in block, block[:60]


# ------------------------------------------------------- names match the product

def test_step_1_documents_exactly_the_execution_cards():
    cards = titles("SUT_KINDS")
    sec = md("sut")[md("sut").index("### How do you run your program?"):md("sut").index("### Execution command")]
    assert re.findall(r"^- \*\*([^*]+)\*\*", sec, re.M) == cards


def test_step_2_documents_exactly_the_input_modes():
    modes = titles("INP_MODES")
    sec = md("inputs")[md("inputs").index("### Where inputs come from"):]
    assert re.findall(r"^- \*\*([^*]+)\*\*", sec[:sec.index(":::\n")], re.M) == modes


def test_step_4_documents_the_presets_checks_and_outcomes():
    text = md("strategy")
    for name in titles("STRAT_CHECKS") + [p for p in re.findall(r'\bt: "([^"]+)"', JS[JS.index("const STRATEGY_PRESETS"):JS.index("// \"5\", \"5s\"")])]:
        assert f"**{name}**" in text, name
    labels = re.findall(r'label: "([^"]+)"', JS[JS.index("const VERDICTS = {"):JS.index("const VORDER")])
    for label in labels:
        assert f"**{label}**" in text, label
    assert "**campaign setup failure**" in text.lower() or "campaign setup failure" in text.lower()


RUN_OPTIONS = ["Equal time", "Equal count", "Time limit", "Number of tests", "Entire corpus",
               "SpreadEx prioritization", "Random order", "All generators", "Best generator", "Best 2 generators",
               "Parallel executions", "Embedding"]


@pytest.mark.parametrize("name", RUN_OPTIONS)
def test_step_5_options_exist_in_the_ui_and_the_guide(name):
    assert name in JS, f"{name} is not in the Workbench any more"
    assert f"**{name}**" in md("run"), name


def test_results_documents_every_tab_and_status():
    text = md("results")
    for name in titles("RESULT_TABS"):
        assert f"**{name}**" in text, name
    statuses = re.findall(r'\[[^\]]*"([A-Z][a-z]+)"\]', JS[JS.index("const RUN_STATUS"):JS.index("function statusPill")])
    for label in statuses + ["Running"]:
        assert f"**{label}**" in text, label


def test_generators_guide_names_every_catalog_generator_with_its_family():
    from spreadex.generators.manager import load_catalog

    text = md("generators")
    family = {"probabilistic": "Probabilistic", "constraint-based": "Constraint-based", "llm-based": "LLM-based"}
    for gen in load_catalog().values():
        row = next((ln for ln in text.splitlines() if ln.startswith(f"| {gen.name} |")), None)
        assert row and family[gen.family] in row, gen.name


# --------------------------------------------------------------- CLI reference

def test_the_cli_reference_is_the_real_parser():
    from spreadex.api.setup import cli_reference

    ref = cli_reference()
    names = [c["name"] for c in ref["commands"]]
    for expected in ("init", "doctor", "run", "example", "demo", "ui", "generators", "runtimes", "record",
                     "replay", "export", "results", "runs"):
        assert expected in names
    assert all(c["help"] for c in ref["commands"]), "internal aliases without help are left out"
    gens = next(c for c in ref["commands"] if c["name"] == "generators")
    assert {s["name"] for s in gens["subcommands"]} == {"list", "status", "install"}


def test_every_command_a_guide_mentions_exists():
    from spreadex.api.setup import cli_reference

    names = {c["name"] for c in cli_reference()["commands"]}
    used = set(re.findall(r"`spreadex (\w+)", all_md()))
    assert used and used <= names, used - names


# ------------------------------------------------------------- accurate claims

def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\n", text) if s.strip()]


def test_cluster_coverage_is_never_said_to_predict_or_guarantee_faults():
    for s in sentences(all_md()):
        if re.search(r"\b(predicts?|guarantees?)\b", s, re.I) and re.search(r"Cluster Coverage|\bCC\b|prioriti", s):
            assert re.search(r"\b(not|never|does not|nor)\b", s), s


def test_live_fuzz4all_and_shared_llm_configuration_are_never_called_available():
    for s in sentences(all_md()):
        if re.search(r"live Fuzz4All|shared LLM configuration", s, re.I):
            assert re.search(r"not (yet )?available|is not available|not available yet|P1|not in this version", s), s


def test_windows_is_never_claimed_as_verified():
    for s in sentences(all_md()):
        if "Windows" in s:
            assert re.search(r"[Uu]nverified|not run|has not", s), s


def test_a_timeout_is_never_called_a_bug_or_defect():
    for s in sentences(all_md()):
        if re.search(r"\btimeout\b", s, re.I) and re.search(r"\b(bug|defect)\b", s, re.I):
            assert re.search(r"\bnot\b", s), s


def test_recorded_inputs_are_described_as_replayed_not_regenerated():
    text = md("generators")
    assert "Replaying gives **exactly those inputs** again; it does not generate new ones" in text
    assert "not a controlled comparison" in text


@pytest.mark.parametrize("pattern", [r"/Users/", r"/home/", r"[A-Z]:\\", r"/var/folders", r"/private/tmp",
                                     r"\bsk-[A-Za-z0-9]{8}", r"RESEARCH/", r"ClusGram/"])
def test_no_local_paths_or_secrets(pattern):
    for f in [*GUIDES.glob("*.md"), GUIDES / "screenshots.json"]:
        assert not re.search(pattern, f.read_text()), f"{f.name}: {pattern}"


# --------------------------------------------------- screenshots stay in step

SHOTS = json.loads((GUIDES / "screenshots.json").read_text())


def test_every_screenshot_is_used_exists_and_is_used_once_listed():
    used = set(re.findall(r"\{\{img:([a-z0-9-]+)\}\}", all_md()))
    assert used == set(SHOTS), (used ^ set(SHOTS))
    for shot_id in SHOTS:
        png = GUIDES / "img" / f"{shot_id}.png"
        assert png.is_file(), shot_id
        head = png.read_bytes()[:24]
        assert head[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", head[16:24])
        assert width == 1280 and 200 < height <= 1100, (shot_id, width, height)
    total = sum((GUIDES / "img" / f"{i}.png").stat().st_size for i in SHOTS)
    assert total < 4_000_000, f"screenshots grew to {total} bytes"


def _selector_exists(selector: str) -> bool:
    m = re.fullmatch(r"\[data-([a-z]+)='([^']+)'\]", selector)
    if m:
        attr, value = m.groups()
        if attr == "tour":
            return f'data-tour="{value}"' in JS or f'tour: "{value}"' in JS
        return f"data-{attr}=" in JS and (value in JS)
    if selector.startswith("."):
        return re.search(rf'class="[^"]*\b{re.escape(selector[1:])}\b', JS) is not None
    if selector.startswith("#"):
        return f'id="{selector[1:]}"' in JS
    return False


@pytest.mark.parametrize("shot_id", sorted(SHOTS))
def test_every_annotated_element_still_exists(shot_id):
    for mark in SHOTS[shot_id]["marks"]:
        assert _selector_exists(mark["selector"]), (shot_id, mark["selector"])
    assert SHOTS[shot_id]["caption"] and SHOTS[shot_id]["project"] in ("fresh", "own", "rhino")


def test_the_capture_script_knows_every_screen():
    script = (ROOT / "scripts" / "docs" / "capture_guides.py").read_text()
    for spec in SHOTS.values():
        assert f'"{spec["screen"]}":' in script, spec["screen"]


# --------------------------------------------------------------------- links

def test_every_contextual_guide_link_resolves():
    links = re.findall(r'guideLink\("([a-z]+)"(?:, "([a-z0-9-]*)")?', JS)
    assert {sec for sec, _ in links} >= set(STEPS) | {"results", "troubleshooting"}
    for sec, anchor in links:
        assert sec in SECTIONS, sec
        if anchor:
            assert anchor in anchors(sec), (sec, anchor)


def test_every_step_title_carries_its_guide_link():
    for title, sec in [("Connect your system under test", "sut"), ("Define the input specification", "inputs"),
                       ("Choose your input generators", "generators"), ("What do you want to detect?", "strategy"),
                       ("Review &amp; run", "run")]:
        assert f'{title} ${{guideLink("{sec}")}}' in JS, title


def test_every_link_inside_the_guides_resolves():
    for target in re.findall(r"\]\(#guide/([a-z]+(?:#[a-z0-9-]+)?)\)", all_md()):
        sec, _, anchor = target.partition("#")
        assert sec in SECTIONS, target
        if anchor:
            assert anchor in anchors(sec), target


def test_home_view_documentation_opens_the_guides():
    assert "onclick=\"go('guides')\">View documentation" in JS


# ----------------------------------------------------------- renderer safety

def _node(expr: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    start = JS.index("const GUIDES = [")
    code = "\n".join([
        "const esc = s => String(s).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));",
        "const ICONS = new Proxy({}, {get: () => '<svg></svg>'});",
        "const S = {};",
        JS[start:JS.index("async function renderGuides")],
        f"process.stdout.write(JSON.stringify({expr}));",
    ])
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_renderer_escapes_markup_and_refuses_unsafe_links():
    html = _node(r"""mdBlocks(["<script>alert(1)</script>", "[x](javascript:alert(1)) [y](#guide/run#common-problems)",
                               "> [!FAIL]", "> <img src=x onerror=alert(1)>"])""")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "javascript:" not in html.replace("[x](javascript:alert(1))", "") or 'href="javascript' not in html
    assert 'href="javascript' not in html and "onerror=alert" not in html.replace("&lt;img src=x onerror=alert(1)&gt;", "")
    assert "openGuide('run', 'common-problems')" in html and "g-fail" in html


def test_the_renderer_builds_tabs_problems_and_collapsed_advanced_sections():
    html = _node(r"""mdBlocks([":::tabs", "::tab A", "one", "::tab B", "two", ":::",
                               ":::problem Broken", "cause: c", "fix: f", ":::", ":::advanced More", "deep", ":::"])""")
    assert html.count('role="tab"') == 2 and "hidden" in html
    assert "Likely cause" in html and "g-prob-fix" in html
    assert "<details class=\"g-adv\">" in html and " open" not in html


def test_on_this_page_sits_under_the_sections_and_screenshots_can_be_enlarged():
    """Two columns, not three: the article gets the width, and "On this page" is in the left column
    after a divider. Every screenshot opens full size."""
    render = JS[JS.index("async function renderGuides"):]
    render = render[:render.index("\n}\n")]
    nav = render[render.index('<nav class="g-nav"'):render.index("</nav>")]
    assert 'class="g-toc"' in nav and "<aside" not in render
    css = (STATIC / "app.css").read_text()
    assert "grid-template-columns: 240px minmax(0, 1fr);" in css
    assert "border-top: 1px solid var(--color-border)" in css[css.index(".g-toc {"):][:300]
    fig = JS[JS.index("function guideFigure"):JS.index("function zoomShot")]
    assert "onclick=\"zoomShot(" in fig and 'class="g-shot"' in fig
    zoom = JS[JS.index("function zoomShot"):JS.index("function cliHtml")]
    assert 'aria-modal", "true"' in zoom and "Escape" in zoom and "opener?.focus" in zoom
