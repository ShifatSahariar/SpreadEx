"""Regression coverage for the empty-project Workbench entry state."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "src/spreadex/api/static/app.js").read_text()
INDEX = (ROOT / "src/spreadex/api/static/index.html").read_text()
CSS = (ROOT / "src/spreadex/api/static/app.css").read_text()


def test_initial_view_has_the_three_project_states():
    assert 'if (!project.configured) return "landing";' in APP
    assert 'return runs.length ? "results" : "setup";' in APP
    assert 'go(initialView(S.project, S.runs));' in APP


def test_landing_enters_the_existing_setup_step_without_config_writes():
    assert "onclick=\"go('setup')\"" in APP
    landing = APP[APP.index("function renderLanding") : APP.index("function renderSteps")]
    assert "/api/config" not in landing
    assert "/api/run" not in landing


def test_landing_contains_the_approved_copy_and_no_demo_endpoint():
    for text in (
        "SpreadEx <span>Workbench</span>",
        "Test compilers, interpreters, parsers, and other",
        "pipeline-art",
        "Quick demo",
        "spreadex demo",
        "Get started",
        "Choose a subject",
        "Configure generators",
    ):
        assert text in APP
    assert "/api/demo" not in APP


def test_every_section_is_reachable_and_the_current_one_is_marked():
    """The start page shows the whole workbench rather than hiding sections.

    Replaces an older assertion that the Setup and Results tabs were *hidden*
    on the landing page: the navigation now lists every section at all times,
    so what matters is that each one resolves and that the current section is
    marked rather than merely styled.
    """
    for tab in ("tab-home", "tab-setup", "tab-generators",
                "tab-executions", "tab-results"):
        assert tab in INDEX, f"{tab} is missing from the shell"
        assert f'el("{tab}").setAttribute("aria-selected"' in APP, (
            f"{tab} never gets aria-selected, so no section is announced as current"
        )


def test_read_only_mode_is_still_stated_on_the_start_page():
    """A workbench that cannot change anything has to say so before the user
    clicks the button that would."""
    assert "S.project?.read_only" in APP
    assert "This Workbench is read-only" in APP
    assert 'onclick="go(\'setup\')" ${readOnly ? "disabled" : ""}' in APP


def test_landing_has_responsive_shared_layout_foundation():
    assert "--content-max" in CSS
    assert "--page-pad" in CSS
    assert "clamp(2.1rem, 3vw, 2.75rem)" in CSS
    # `clip` rather than `hidden`: both stop sideways scrolling, but hidden
    # makes the page a scroll container and breaks position: sticky.
    assert "overflow-x: clip" in CSS
    assert "@media (max-width: 700px)" in CSS
    assert "@media (max-width: 430px)" in CSS


# ------------------------------------------------- the start page's visuals

def test_the_start_page_uses_svg_icons_not_font_glyphs():
    """A glyph like "▥" renders differently on every platform, cannot take
    a theme colour, and is read aloud as punctuation. Every icon on the start
    page is inline SVG inheriting currentColor."""
    import re

    rendered = APP[APP.index("function renderLanding"):APP.index("function showDemoHint")]
    glyphs = set(re.findall(r"[■-◿←-⇿☀-➿❖⬀-⯿]",
                            rendered))
    assert not glyphs, f"decorative glyphs left in the start page: {glyphs}"
    assert rendered.count("ICONS.") >= 12, "the icon set is barely used"


def test_every_icon_inherits_colour_and_is_hidden_from_assistive_tech():
    """An icon beside its own label is decoration; announcing it twice is
    noise."""
    icons = APP[APP.index("const ICONS = {"):].split("};", 1)[0]
    assert 'stroke="currentColor"' in APP
    assert 'aria-hidden="true"' in APP
    assert "focusable=\"false\"" in APP, "IE/Edge focus the SVG without this"
    for name in ("home", "folder", "sliders", "play", "download", "gear",
                 "book", "arrow", "file", "sparkle", "shield", "chart",
                 "list", "search", "tag", "report"):
        assert f"{name}:" in icons, f"ICONS.{name} is missing"


def test_the_page_is_centred_rather_than_pinned_to_the_left():
    """`main` carried a max-width with no auto margin, so on a wide display the
    whole workbench hugged the left edge."""
    assert "margin-inline: auto" in CSS
    main_rule = CSS[CSS.index("main { padding"):]
    main_rule = main_rule[:main_rule.index("}") + 1]
    assert "margin-inline: auto" in main_rule, main_rule
    assert "margin-inline: auto" in CSS[CSS.index(".dashboard-home {"):][:220]


def test_the_decorative_band_cannot_make_the_page_scroll_sideways():
    """The band is deliberately wider than the viewport. Without clipping it
    makes the document horizontally scrollable, which moves the content -- and
    a decoration that moves the content is not a decoration."""
    assert "overflow-x: clip" in CSS
    assert "overflow-x: hidden" not in CSS, (
        "hidden would create a scroll container and break position: sticky"
    )


def test_the_layout_adapts_without_hiding_navigation():
    """Below the hero's two-column width the page stacks, and the section list
    scrolls rather than being clipped -- clipping would hide destinations."""
    assert "@media (max-width: 1020px)" in CSS
    assert "@media (max-width: 620px)" in CSS
    narrow = CSS[CSS.index("@media (max-width: 760px)"):]
    assert "overflow-x: auto" in narrow, "the section list must stay reachable"


def test_decoration_is_dropped_for_readers_who_asked_for_less():
    assert "prefers-reduced-motion: reduce" in CSS
