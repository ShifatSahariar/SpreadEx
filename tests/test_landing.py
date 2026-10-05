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
        "workflow-figure",
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
    assert rendered.count("ICONS.") >= 8, "the icon set is barely used"


def test_every_icon_inherits_colour_and_is_hidden_from_assistive_tech():
    """An icon beside its own label is decoration; announcing it twice is
    noise."""
    icons = APP[APP.index("const ICONS = {"):].split("};", 1)[0]
    assert 'stroke="currentColor"' in APP
    assert 'aria-hidden="true"' in APP
    assert "focusable=\"false\"" in APP, "IE/Edge focus the SVG without this"
    for name in ("home", "folder", "sliders", "play", "download", "gear",
                 "playSolid", "book", "arrow", "chart"):
        assert f"{name}:" in icons, f"ICONS.{name} is missing"


def test_no_icon_is_defined_and_never_used():
    """The nine-stage diagram used to draw its own icons from this set. When it
    became one SVG, seven of them were left behind with no caller."""
    import re

    block = APP[APP.index("const ICONS = {"):].split("};", 1)[0]
    defined = re.findall(r"^  (\w+):", block, flags=re.M)
    used_in_js = set(re.findall(r"ICONS\.(\w+)", APP))
    used_in_html = set(re.findall(r'data-icon="(\w+)"', INDEX))
    dead = [n for n in defined if n not in used_in_js | used_in_html]
    assert not dead, f"defined but never used: {dead}"


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
    narrow = CSS[CSS.index("@media (max-width: 960px)"):]
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


def test_the_landing_styles_are_defined_exactly_once():
    """Two complete definitions of the hero, the pipeline and the cards is how
    a fix comes to need a third: the later block silently won, and editing the
    earlier one did nothing.

    Only BASE rules are counted. In this stylesheet a base rule starts at
    column 0 and a responsive override is indented inside a media query, so a
    legitimate override is not mistaken for a duplicate.
    """
    base = [ln for ln in CSS.splitlines() if ln and not ln[0].isspace()]
    for selector in (".hero-actions {", ".workflow {", ".start-cards {",
                     ".landing-hero {", ".hero-action {",
                     ".dashboard-home .landing-intro {"):
        hits = [ln for ln in base if ln.startswith(selector)]
        assert len(hits) == 1, f"{selector} has {len(hits)} base rules: {hits}"


# ------------------------------------------------------- the workflow diagram

WORKFLOW = APP[APP.index("const WORKFLOW_SVG = `"):].split("`;", 1)[0]


def test_the_workflow_is_an_inline_svg_that_scales_with_its_column():
    """No fixed width or height on the root: the box follows its container and
    the viewBox supplies the aspect ratio. A fixed size is what would make it
    overflow a narrow window or sit tiny in a wide one."""
    import re

    root = re.search(r"<svg[^>]*>", WORKFLOW).group(0)
    assert "viewBox=" in root
    assert not re.search(r'\swidth="', root) and not re.search(r'\sheight="', root), root
    assert 'role="img"' in root and "aria-label=" in root, "it needs a text equivalent"
    rule = CSS[CSS.index(".workflow {"):]
    rule = rule[:rule.index("}") + 1]
    assert "width: 100%" in rule and "height: auto" in rule, rule


def test_the_workflow_shows_all_nine_stages_as_real_text():
    """Real text, not outlines or an image: selectable, searchable, and carried
    by the page's own font."""
    for stage in ("Grammar", "Generate", "Check", "Analyze", "Prioritize",
                  "Execute", "Observe", "Classify", "Save &amp; Report"):
        assert f">{stage}</text>" in WORKFLOW, stage
    assert "font-family" not in WORKFLOW, "the diagram should use the page font"


def test_every_connector_that_uses_a_gradient_can_actually_be_painted():
    """The supplied file drew the Prioritize -> Execute -> Observe -> Classify
    connectors with an objectBoundingBox gradient on perfectly horizontal
    paths. A zero-height bounding box paints nothing, so they were invisible.
    Every gradient used as a stroke must be in user space."""
    import re

    for gid in set(re.findall(r'stroke="url\(#(wf-[\w-]+)\)"', WORKFLOW)):
        tag = re.search(rf'<linearGradient id="{gid}"[^>]*>', WORKFLOW)
        assert tag, f"{gid} is used but not defined"
        assert 'gradientUnits="userSpaceOnUse"' in tag.group(0), (
            f"{gid} uses bounding-box units; a horizontal line cannot show it"
        )


def test_there_is_an_arrowhead_at_every_hand_off():
    """Nine stages, eight hand-offs, one chevron on each. The supplied file had
    four small filled triangles and none into Prioritize or between the bottom
    row's stages."""
    import re

    chevrons = re.findall(r'<path d="M[\d.]+ [\d.]+ L[\d.]+ [\d.]+ L[\d.]+ [\d.]+" fill="none"'
                          r'[^>]*stroke-linejoin="round"/>', WORKFLOW)
    assert len(chevrons) == 8, len(chevrons)
    assert "l18 11 -18 11z" not in WORKFLOW, "the old filled triangles are gone"


def test_the_workflow_cannot_collide_with_the_pages_own_ids():
    """Inline SVG shares the document's id namespace, so a gradient called
    `shadow` or `bg` would silently capture someone else's reference."""
    import re

    ids = re.findall(r'\bid="([^"]+)"', WORKFLOW)
    assert ids and all(i.startswith("wf-") for i in ids), ids
    for ref in re.findall(r"url\(#([^)]+)\)", WORKFLOW):
        assert ref in ids, f"url(#{ref}) points at nothing"


def test_the_workflow_follows_the_theme_in_both_ways_dark_mode_is_reached():
    """An explicit dark choice, and the system preference with no choice made.
    Handling only the first leaves anyone on a dark system with glaring cards."""
    for part in (':root[data-theme="dark"] .workflow .wf-node',
                 ':root:not([data-theme="light"]) .workflow .wf-node',
                 ':root[data-theme="dark"] .workflow .wf-labels',
                 ':root:not([data-theme="light"]) .workflow .wf-labels'):
        assert part in CSS, part
    assert WORKFLOW.count('class="wf-node"') == 9, "every card must be themeable"


def test_the_workflow_stays_readable_on_a_phone_without_widening_the_page():
    """Pure scaling would put a phone's labels at ~6px. Below 640px the diagram
    holds a 600px floor inside its own scroller, so it pans while the page
    stays put."""
    phone = CSS[CSS.index("@media (max-width: 640px) {\n  .workflow-figure"):]
    phone = phone[:phone.index("\n}")]
    assert "min-width: 600px" in phone
    assert "overflow-x: auto" in phone
    assert 'tabindex="0"' in APP[APP.index("workflow-figure"):][:200], (
        "a scrollable region must be reachable from the keyboard"
    )


def test_the_hero_gives_the_diagram_enough_width_before_it_stacks():
    """Side by side it needs ~590px for 10px labels; narrower and it falls to
    8.8px (measured at 1105). So the hero stacks while there is still room."""
    assert "@media (max-width: 1180px)" in CSS
    assert "grid-template-columns: minmax(0, 26rem) minmax(0, 1fr)" in CSS


def test_the_stylesheet_has_balanced_braces():
    """A stray `}` makes the parser treat the NEXT rule's selector as invalid
    and drop it. One was left behind when the logo animation was restored; it
    was harmless only because it happened to be the last thing in the file."""
    import re

    clean = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert clean.count("{") == clean.count("}"), (clean.count("{"), clean.count("}"))


def test_no_selector_list_is_left_dangling():
    """Removing the last line of a comma-separated selector list leaves the
    comma attached to whatever follows, which swallows the next block whole."""
    import re

    clean = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert not re.search(r",\s*(@|\n\s*@|\Z)", clean), "a selector list ends in a comma"
    assert not re.search(r",\s*\n\s*\n", clean), "a selector list ends before a blank line"


# ------------------------------------------------------------------ the header

def test_no_stub_selector_swallows_the_at_rule_after_it():
    """A selector with its body deleted -- say `:root[data-theme="dark"] ` --
    sits directly before the next block, so the parser reads them as ONE
    qualified rule with an invalid selector and discards the lot. That is how
    the whole compact-header @media block silently vanished: balanced braces,
    no trailing comma, and still gone. The only symptom was a layout that did
    not respond.

    Any top-level prelude with an at-rule buried inside it is the signature.
    """
    import re

    clean = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), CSS, flags=re.S)
    depth, start, bad = 0, 0, []
    for i, ch in enumerate(clean):
        if ch == "{":
            if depth == 0:
                prelude = clean[start:i].strip()
                if "@" in prelude and not prelude.startswith("@"):
                    bad.append((clean[:i].count("\n") + 1, prelude[:70].replace("\n", " ")))
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                start = i + 1
    assert not bad, f"a stub selector is swallowing the rule after it: {bad}"


def test_the_logo_goes_home_by_the_same_route_the_home_button_does():
    """The same handler, not a lookalike -- so the two cannot drift apart, and
    both leave the app in the same state (checked in the browser)."""
    import re

    brand = re.search(r'<button[^>]*id="brand"[^>]*>', INDEX).group(0)
    home = re.search(r'<button[^>]*id="tab-home"[^>]*>', INDEX).group(0)
    handler = lambda tag: re.search(r'onclick="([^"]+)"', tag).group(1)
    assert handler(brand) == handler(home) == "go('landing')", (brand, home)


def test_the_logo_is_a_button_with_a_name_and_a_decorative_image():
    """A button and not a link: a link invites "open in new tab", which lands
    on a page with no access token. The name is on the button, so the image
    inside it must not be announced a second time."""
    import re

    block = INDEX[INDEX.index('id="brand"'):INDEX.index("</button>", INDEX.index('id="brand"'))]
    assert 'type="button"' in INDEX[INDEX.index('id="brand"') - 80:INDEX.index('id="brand"') + 20]
    assert 'aria-label="SpreadEx, go to Home"' in INDEX
    assert 'aria-hidden="true"' in re.search(r'<svg class="brand-logo"[^>]*>', block).group(0)
    assert "<a " not in block


def test_the_project_path_is_out_of_the_header_but_one_hover_away():
    """Removed from the bar, where it competed with the menu; kept in the
    badge's tooltip so the information is not lost."""
    assert 'id="project"' not in INDEX
    assert ".project" not in CSS
    assert 'el("project")' not in APP
    assert "Running locally for ${S.project.root}" in APP


def test_the_local_badge_stays_but_is_small():
    rule = CSS[CSS.index(".local-badge {"):]
    rule = rule[:rule.index("}") + 1]
    assert "font-size: 10px" in rule, rule
    assert "padding: 2px 7px" in rule, rule
    assert ">LOCAL</span>" in INDEX.replace("\n", "").replace("    ", "")


def test_the_header_is_brand_menu_then_tools_in_one_row():
    """Brand and menu share a row; the divider, theme toggle and settings sit
    after the menu as in the design -- the theme toggle used to be stuck in
    front of Home."""
    order = [INDEX.index(m) for m in ('id="brand"', 'id="local-badge"', '<nav class="tabs"',
                                      'id="tab-home"', 'id="tab-results"',
                                      'class="topbar-tools"', 'class="topbar-sep"',
                                      'id="theme"', 'id="settings"')]
    assert order == sorted(order), order
    nav = INDEX[INDEX.index('<nav class="tabs"'):INDEX.index("</nav>")]
    assert 'id="theme"' not in nav and 'id="settings"' not in nav


def test_the_header_wraps_only_when_it_genuinely_cannot_fit():
    """~950px is what one row needs (measured: 823px of content, three 18px
    gaps, 56px of padding and a 15px scrollbar). Below 960px the menu takes its
    own row; wrapping any later strands the tools alone on a line."""
    block = CSS[CSS.index("@media (max-width: 960px)"):]
    block = block[:block.index("\n}")]
    assert ".tabs { order: 4; flex-basis: 100%" in block
    assert ".topbar-tools { margin-left: auto; }" in block
    assert ".topbar-sep { display: none; }" in block, "a divider with nothing beside it"
