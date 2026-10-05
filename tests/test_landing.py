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
    assert '${readOnly ? "disabled" : ""}' in APP, (
        "the primary action must be disabled when nothing can be changed"
    )


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


# --------------------------------------------- hero: mark, lede and actions

def test_the_two_hero_actions_are_sized_by_the_grid_not_by_their_labels():
    """Both must match in width and height at every viewport. Side by side
    they came out 244px each with both labels wrapping, so they stack: one
    column makes the width identical by construction, and `grid-auto-rows: 1fr`
    makes the height identical even though only one has a second line."""
    rule = CSS[CSS.index(".hero-actions {"):]
    rule = rule[:rule.index("}") + 1]
    assert "grid-template-columns: 1fr" in rule, rule
    assert "grid-auto-rows: 1fr" in rule, rule
    assert "align-items: stretch" in rule, rule
    assert CSS.count(".hero-actions {") == 1, "a second rule would fight this one"


def test_the_lede_and_the_actions_share_one_measure():
    """Three different widths stacked up read as three blocks; one measure
    reads as a column."""
    assert "--hero-col" in CSS
    intro = CSS[CSS.index(".dashboard-home .landing-intro {"):]
    assert "--hero-col" in intro[:intro.index("}")], (
        "the measure must be declared on the shared parent, or the lede cannot "
        "see it -- custom properties cascade down, not sideways"
    )
    assert "max-width: var(--hero-col)" in CSS
    assert "text-wrap: balance" in CSS, "even line lengths, not a short widow"


def test_the_brand_mark_is_the_one_from_the_research_webapp():
    """Same geometry as the original: four green squares at the corners, four
    orange circles on the cardinals, a two-part red centre, and eight spokes."""
    mark = APP[APP.index("const BRAND_MARK"):APP.index("const ICONS")]
    assert mark.count('class="logo-green"') == 4
    assert mark.count('class="logo-orange"') == 4
    assert mark.count('class="logo-red"') == 2
    assert mark.count("logo-line-green") == 4 and mark.count("logo-line-orange") == 4
    assert 'viewBox="0 0 60 60"' in mark
    assert 'aria-hidden="true"' in mark, "decoration beside a heading that says the same"


def test_the_mark_keeps_the_research_webapp_s_original_loop():
    """The 5s cycle from webapp/static/styles.css, timings unchanged: the mark
    builds up, holds to 78%, collapses, and starts again.

    An earlier version of this file played it once and held. That was changed
    back on request -- the looping build is the identity the tool has always
    had, and keeping it identical to the research webapp is the point.
    """
    for stage in ("mark-red", "mark-green", "mark-orange",
                  "mark-line-green", "mark-line-orange"):
        assert f"@keyframes {stage}" in CSS, stage
        decl = CSS[CSS.index(f"animation: {stage}"):]
        decl = decl[:decl.index(";")]
        assert "5s" in decl and "infinite" in decl, f"{stage} no longer loops: {decl}"

    # The staging is what makes it read as an assembly rather than a flicker:
    # red leads, the green squares follow, the orange circles last.
    def first_visible(stage):
        frames = " ".join(CSS[CSS.index(f"@keyframes {stage}"):].split())
        return frames[:frames.index("{", frames.index("{") + 1)]

    assert "8%" in first_visible("mark-green"), "green should wait for red"
    assert "16%" in first_visible("mark-orange"), "orange should wait for green"


def test_the_looping_mark_still_holds_still_for_reduced_motion():
    """A mark that rebuilds every five seconds is exactly what someone who
    asked for less movement does not want."""
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("\n}")]
    assert ".hero-mark" in block
    assert "animation: none" in block
    assert "opacity: 1" in block, "and it must be left visible, not invisible"


def test_the_pipeline_folds_rather_than_running_off_the_page():
    """Between the stacking breakpoint and a wide desktop the nine stages are
    wider than their column. nowrap let them overflow the page edge."""
    rule = CSS[CSS.index(".pipeline-row {"):]
    rule = rule[:rule.index("}") + 1]
    assert "flex-wrap: wrap" in rule, rule
    assert "nowrap" not in rule, rule


def test_the_landing_styles_are_defined_exactly_once():
    """Two complete definitions of the hero, the pipeline and the cards is how
    a fix comes to need a third: the later block silently won, and editing the
    earlier one did nothing.

    Only BASE rules are counted. In this stylesheet a base rule starts at
    column 0 and a responsive override is indented inside a media query, so a
    legitimate override is not mistaken for a duplicate.
    """
    base = [ln for ln in CSS.splitlines() if ln and not ln[0].isspace()]
    for selector in (".hero-actions {", ".pipeline-row {", ".start-cards {",
                     ".landing-hero {", ".hero-action {",
                     ".dashboard-home .landing-intro {"):
        hits = [ln for ln in base if ln.startswith(selector)]
        assert len(hits) == 1, f"{selector} has {len(hits)} base rules: {hits}"
