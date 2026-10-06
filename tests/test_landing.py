"""Regression coverage for the empty-project Workbench entry state."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "src/spreadex/api/static/app.js").read_text()
INDEX = (ROOT / "src/spreadex/api/static/index.html").read_text()
CSS = (ROOT / "src/spreadex/api/static/app.css").read_text()


def test_initial_view_lands_in_the_agreed_order():
    """Active run (handled first in the bootstrap) -> a saved view that is still valid -> the
    latest campaign -> Review & run for a configured project -> Setup for a new one."""
    iv = APP[APP.index("function initialView"):APP.index("function savedViewValid")]
    order = ['savedViewValid(saved', 'runs.length', 'project.configured', 'step: "sut"']
    positions = [iv.index(x) for x in order]
    assert positions == sorted(positions)
    assert 'current: runs[0].run_id' in iv and 'step: "run"' in iv
    boot = APP[APP.index("(async function () {"):]
    assert boot.index('"/api/active"') < boot.index("initialView(")
    assert "initialView(S.project, S.runs, loadView(), stepReachable)" in boot


def test_landing_enters_the_existing_setup_step_without_config_writes():
    assert "onclick=\"go('setup')\"" in APP
    landing = APP[APP.index("function renderLanding") : APP.index("function renderSteps")]
    assert "/api/config" not in landing
    assert "/api/run" not in landing


def test_landing_contains_the_approved_copy_and_no_demo_endpoint():
    for text in (
        "<span class=\"t1\">SpreadEx</span> <span class=\"t2\">Workbench</span>",
        "Generate, prioritize, and run tests for compilers, interpreters, parsers,",
        "workflow-figure",
        "Quick demo",
        "spreadex demo",
        "Get started",
        "Choose a subject",
        "Configure generators",
    ):
        assert text in APP
    # The demo button opens the real bundled demo through the server; it is not a canned page.
    assert '"/api/demo/open"' in APP and "location.href = r.url" in APP


def test_every_section_is_reachable_and_the_current_one_is_marked():
    """The start page shows the whole workbench rather than hiding sections.

    Replaces an older assertion that the Setup and Results tabs were *hidden*
    on the landing page: the navigation now lists every section at all times,
    so what matters is that each one resolves and that the current section is
    marked rather than merely styled.
    """
    for tab in ("tab-home", "tab-setup", "tab-results"):
        assert tab in INDEX, f"{tab} is missing from the shell"
        assert f'el("{tab}").setAttribute("aria-selected"' in APP, (
            f"{tab} never gets aria-selected, so no section is announced as current"
        )
    # Executions and Generators duplicated other entries and were never marked current.
    assert "tab-executions" not in INDEX and "tab-generators" not in INDEX


def test_every_header_control_calls_a_function_that_exists():
    import re
    header = INDEX[INDEX.index("<header"):INDEX.index("</header>")]
    handlers = re.findall(r'onclick="([^"]+)"', header)
    assert handlers
    for h in handlers:
        for fn in re.findall(r"(\w+)\(", h):
            assert re.search(rf"(async )?function {fn}\(", APP), f"{fn} (from {h!r}) is not defined"


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


def _media(width: int, marker: str) -> str:
    """The media block at `width` whose body contains `marker`.

    Several blocks share a width (the header and the step bar both change at
    960px; the hero and the step tiles at 1180px), so finding "the" block by
    its query alone silently reads whichever comes first.
    """
    needle = f"@media (max-width: {width}px)"
    start = 0
    while True:
        i = CSS.index(needle, start)
        end = CSS.index("\n}", i) if "{\n" in CSS[i:i + len(needle) + 4] else CSS.index("}", i) + 1
        body = CSS[i:end]
        if marker in body:
            return body
        start = i + len(needle)


# ------------------------------------------------- the start page's visuals

def test_the_start_page_uses_svg_icons_not_font_glyphs():
    """A glyph like "▥" renders differently on every platform, cannot take
    a theme colour, and is read aloud as punctuation. Every icon on the start
    page is inline SVG inheriting currentColor."""
    import re

    rendered = APP[APP.index("function renderLanding"):APP.index("// ---- opening the demo (Home)")]
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
    for name in ("home", "folder", "sliders", "chart", "gear",
                 "book", "arrow", "chart"):
        assert f"{name}:" in icons, f"ICONS.{name} is missing"


def test_no_icon_is_defined_and_never_used():
    """The nine-stage diagram used to draw its own icons from this set. When it
    became one SVG, seven of them were left behind with no caller."""
    import re

    block = APP[APP.index("const ICONS = {"):].split("};", 1)[0]
    defined = re.findall(r"^  (\w+):", block, flags=re.M)
    used_in_js = set(re.findall(r"ICONS\.(\w+)", APP))
    # The wizard's steps name their icon ("icon: \"terminal\"") and look it up at
    # render time, because ICONS is declared further down the file.
    used_in_js |= set(re.findall(r'icon: "(\w+)"', APP))
    # Language logos name a Lucide glyph the same way ("lucide":"database").
    used_in_js |= set(re.findall(r'"?lucide"?\s*:\s*"(\w+)"', APP))
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
    narrow = _media(960, ".tabs { order: 4")
    assert "overflow-x: auto" in narrow, "the section list must stay reachable"


def test_decoration_is_dropped_for_readers_who_asked_for_less():
    assert "prefers-reduced-motion: reduce" in CSS


# --------------------------------------------- hero: mark, lede and actions

def test_the_two_hero_actions_are_sized_by_the_grid_not_by_their_labels():
    """Both must match in width and height at every viewport. Side by side
    they came out 244px each with both labels wrapping, so they stack: one
    column makes the width identical by construction, and `grid-auto-rows: 1fr` keeps both
    cards the same height (the setup card has a subtitle now, so neither is padded out)."""
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
    assert 'viewBox="11 11 38 38"' in mark, "cropped to the drawing, so it aligns with the column"
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
    assert "@media (max-width: 1180px) {\n  .landing-hero { grid-template-columns: minmax(0, 1fr)" in CSS
    # 42 / 58: the diagram explains SpreadEx, so it gets the larger share, with a 48-64px gutter.
    assert "grid-template-columns: minmax(0, 42fr) minmax(0, 58fr)" in CSS
    assert "gap: clamp(48px, 4.5vw, 64px)" in CSS


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
    block = _media(960, ".tabs { order: 4")
    assert ".tabs { order: 4; flex-basis: 100%" in block
    assert ".topbar-tools { margin-left: auto; }" in block
    assert ".topbar-sep { display: none; }" in block, "a divider with nothing beside it"


# ------------------------------------------------------- the "Get started" cards

import re as _re

_LANDING = APP[APP.index("function renderLanding"):APP.index("// ---- opening the demo (Home)")]
_STEPS = _re.findall(
    r'\{ n: (\d), tone: "(\w+)",\s*icon: ICONS\.(\w+),\s*title: "([^"]+)",\s*'
    r'body: "([^"]+)",\s*tip: ((?:"[^"]*"\s*\+?\s*)+)\}', _LANDING)


def _tip(raw: str) -> str:
    return "".join(_re.findall(r'"([^"]*)"', raw))


def test_there_are_four_steps_in_order_each_with_its_own_colour():
    assert [(n, tone) for n, tone, *_ in _STEPS] == [
        ("1", "green"), ("2", "blue"), ("3", "orange"), ("4", "purple")]


def test_the_face_of_each_card_is_precise_and_the_guidance_lives_in_the_tooltip():
    """Two layers on purpose: a short line saying WHAT on the card, a sentence
    or two saying HOW in the (i). The tip is bounded too -- measured, at 133
    characters it fills 209x120px inside a 233px card, and the earlier 250-char
    version ran nine lines and hung out of the bottom."""
    for n, _tone, _icon, title, body, tip_raw in _STEPS:
        tip = _tip(tip_raw)
        assert len(body) <= 50, f"card {n} subtext is not precise ({len(body)}): {body}"
        assert len(tip) <= 145, f"card {n} tooltip will not fit the card ({len(tip)})"
        assert len(tip) > len(body), f"card {n}: the tooltip adds nothing to the subtext"
        assert tip != body and title not in body


def test_the_card_copy_claims_only_what_the_tool_does():
    """An earlier version promised "coverage, mutation score and input
    diversity". Mutation testing and code coverage live in the research
    repository; v0.1 does neither. It also offered "a built-in system" with no
    picker to choose one -- there is the bundled demo, and the copy now says so."""
    text = " ".join(f"{body} {_tip(tip)}" for *_, body, tip in _STEPS).lower()
    for claim in ("mutation", "code coverage", "built-in system"):
        assert claim not in text, f"the cards promise {claim!r}, which v0.1 does not do"
    assert "spreadex demo" in text, "the way to a first run should be on the page"


def test_each_card_has_the_design_s_parts_and_a_properly_wired_tooltip():
    card = _LANDING[_LANDING.index("const card = c =>"):_LANDING.index('el("view").innerHTML')]
    for part in ('class="sc-num"', 'class="start-icon"', 'class="sc-info"',
                 'class="sc-tip"', '<h3 class="sc-title">', 'type="button"'):
        assert part in card, part
    # The button names itself, points at its tooltip, and reports whether it is open.
    assert 'aria-label="More about: ${c.title}"' in card
    assert 'aria-describedby="tip-${c.n}"' in card and 'id="tip-${c.n}"' in card
    assert 'aria-expanded="false"' in card and 'role="tooltip"' in card
    # The tooltip must directly follow its button, or the `+` selector cannot see it.
    assert card.index("sc-info") < card.index("sc-tip")
    assert "ICONS.help" in card


def test_the_tooltip_can_be_dismissed_without_moving_the_pointer():
    """WCAG 1.4.13: content shown on hover must be dismissible without moving
    the pointer. After a click the pointer is still on the (i), so hover alone
    holds the tooltip open; Escape has to override it."""
    for needle in ("function dismissTips", "tip-dismissed", 'e.key === "Escape"',
                   'document.addEventListener("click", closeTips)',
                   'document.addEventListener("focusin"', 'document.addEventListener("pointerover"'):
        assert needle in APP, needle
    assert "relatedTarget" in APP, "must only reset when the pointer arrives afresh"
    # Existing is not enough: Escape must actually CALL it. Calling closeTips
    # instead clears the pinned state but leaves a hovered tooltip showing,
    # which is the exact gap this exists to close.
    assert 'if (e.key === "Escape") dismissTips();' in APP
    assert ".start-card:not(.tip-dismissed) .sc-info:hover + .sc-tip" in CSS
    assert ".start-card:not(.tip-dismissed) .sc-info:focus-visible + .sc-tip" in CSS


def test_touch_can_open_the_tooltip_because_safari_does_not_focus_a_tapped_button():
    assert "function toggleTip" in APP and "event.stopPropagation()" in APP
    assert ".start-card.tip-open .sc-tip" in CSS


def test_a_tooltip_cannot_be_hidden_behind_the_card_below_it():
    """Cards are separate stacking contexts, so in two columns a later card
    would paint over an earlier card's tooltip. The active card is lifted."""
    assert ".start-card:hover, .start-card:focus-within, .start-card.tip-open { z-index: 5; }" in CSS


def test_every_card_has_its_own_colour_shade_along_the_bottom():
    """The tinted wave is the design's signature. Each tone defines its own, and
    the wave sits BEHIND the text so it can never reduce a word's contrast."""
    for tone in ("green", "blue", "orange", "purple"):
        rule = _re.search(rf"^\.{tone}-card, \.tone-{tone} \{{[^}}]*\}}", CSS, flags=_re.M).group(0)
        for var in ("--tone:", "--badge:", "--tone-wave:", "--tone-edge:"):
            assert var in rule, f"{tone}-card has no {var}"
    wave = CSS[CSS.index(".start-card::after {"):]
    wave = wave[:wave.index("}") + 1]
    assert "z-index: -1" in wave and "mask:" in wave and "-webkit-mask:" in wave, wave
    assert "isolation: isolate" in CSS[CSS.index(".start-card {"):][:900]


def test_the_cards_theme_through_the_page_surface_not_fixed_pastels():
    """A hard-coded light tint looked fine in light mode and glared in dark.
    Deriving the tile from the tone and the page surface works in both."""
    tile = CSS[CSS.index(".start-icon {"):]
    tile = tile[:tile.index("}") + 1]
    assert "color-mix(in srgb, var(--tone)" in tile and "var(--color-surface)" in tile, tile


def test_the_arrows_live_in_the_gaps_and_go_away_when_the_cards_stack():
    cards = CSS[CSS.index(".start-cards {"):]
    cards = cards[:cards.index("}") + 1]
    assert cards.count("auto") == 3, "three arrow tracks between four cards"
    assert "minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr)" in cards
    stacked = _media(1180, ".start-cards")
    assert ".card-arrow { display: none; }" in stacked, "a 2x2 grid has no order to point along"


def test_get_started_is_smaller_than_it_was():
    heading = CSS[CSS.index(".section-heading h2 {"):]
    heading = heading[:heading.index("}") + 1]
    assert "clamp(1.15rem, 1.9vw, 1.45rem)" in heading, heading
    assert "clamp(1.45rem, 2.6vw, 2rem)" not in CSS, "the old, larger size is still in the sheet"


def test_the_tooltip_respects_reduced_motion():
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("\n}")]
    assert ".sc-tip { transition: none;" in block



# ---------------------------------------------------------------- the step bar

_GLOBAL = APP[APP.index("const STEPS = ["):].split("];", 1)[0]
_WIZARD = _re.findall(
    r'\{ id: "(\w+)",\s*n: (\d), tone: "(\w+)",\s*icon: "(\w+)",\s*t: "([^"]+)",\s*d: "([^"]+)" \}',
    _GLOBAL)
_RENDER = APP[APP.index("function renderSteps()"):APP.index("// ------------------------------------------------------ config helpers")]


def test_the_wizard_has_five_steps_each_with_its_own_colour_and_icon():
    assert [(i, n, tone, icon) for i, n, tone, icon, *_ in _WIZARD] == [
        ("sut", "1", "green", "terminal"), ("grammar", "2", "blue", "doc"),
        ("generators", "3", "purple", "sliders"), ("strategy", "4", "orange", "shield"),
        ("run", "5", "red", "playOutline")]


def test_every_step_icon_exists():
    """Looked up by name at render time, so a typo is a blank tile, not an error."""
    icons = APP[APP.index("const ICONS = {"):].split("};", 1)[0]
    for _id, _n, _tone, icon, *_ in _WIZARD:
        assert f"  {icon}:" in icons, f"ICONS.{icon} is not defined"


def test_the_step_icons_are_looked_up_not_referenced_before_they_exist():
    """STEPS is at the top of the file and ICONS is a const further down, so
    `icon: ICONS.terminal` would read it in its temporal dead zone and take the
    whole page down on load."""
    assert "icon: ICONS." not in _GLOBAL
    assert "ICONS[s.icon]" in _RENDER


def test_the_current_step_is_marked_for_assistive_technology_with_the_right_value():
    """`aria-current` takes `step` for a step in a sequence. The old bar wrote
    the string "true"/"false" onto every button, so the page announced all five
    as current-or-not instead of naming the one that is."""
    assert "aria-current=\"step\"" in _RENDER
    assert 'aria-current="${' not in _RENDER, "it must be omitted, not set to false"
    assert '[aria-current="true"]' not in CSS.split("/* ------------------------------------------------------- wizard steps")[1][:3500]
    assert '<nav class="steps" id="steps" aria-label="Setup steps">' in INDEX
    assert '<ol class="steps-row">' in _RENDER and "step-item" in _RENDER


def test_a_dash_joins_each_pair_of_steps_grey_until_the_step_before_it_is_done():
    """Four dashes between five steps, none after the last. Grey by default; green once the step
    before it is finished -- the green is the brand green, not the step's own tone."""
    assert "i < STEPS.length - 1" in _RENDER
    link = CSS[CSS.index(".step-link {"):]
    link = link[:link.index("}") + 1]
    assert "var(--color-muted)" in link and "var(--tone)" not in link, link
    on = CSS[CSS.index(".step-link.on {"):]
    on = on[:on.index("}") + 1]
    assert "var(--color-primary)" in on and "var(--tone)" not in on
    assert '${done[i] ? "on" : ""}' in _RENDER
    assert 'class="step-item tone-${s.tone}' in _RENDER, "every step still needs its tone"

def test_all_five_boxes_are_exactly_the_same_size():
    """Each step's width includes the link after it, and the last step has none,
    so it ran a link-width wider than the rest -- measured 248px against 240px,
    which read as "some boxes bigger". The last step reserves the link's width."""
    assert "--link-w:" in CSS
    assert ".step-item:last-child::after { content: \"\"; flex: none; width: var(--link-w); }" in CSS
    link = CSS[CSS.index(".step-link {"):]
    assert "width: var(--link-w)" in link[:link.index("}")], "the link and the reserved space must agree"
    assert ".step-item { display: flex; align-items: center; flex: 1 1 0;" in CSS, (
        "equal flex bases are what make equal boxes"
    )


def test_every_icon_tile_carries_its_tone_but_the_number_is_grey_until_done_or_current():
    """The design tints all five tiles; colour on the NUMBER is what says progress."""
    tile = CSS[CSS.index(".step-ico {"):]
    tile = tile[:tile.index("}") + 1]
    assert "color: var(--tone)" in tile and "color-mix(in srgb, var(--tone)" in tile, tile
    badge = CSS[CSS.index(".step .n {"):]
    badge = badge[:badge.index("}") + 1]
    assert "var(--tone)" not in badge, "a future step's number must be grey"
    lit = CSS[CSS.index(".step-item.done .n, .step[aria-current=\"step\"] .n {"):]
    lit = lit[:lit.index("}") + 1]
    assert "var(--tone)" in lit

def test_the_current_step_is_outlined_and_a_little_bigger_without_moving_the_others():
    """A transform takes no layout space, so the other four neither shrink nor shift."""
    current = CSS[CSS.index('.step[aria-current="step"] {'):]
    current = current[:current.index("}") + 1]
    assert "transform: scale(1.04)" in current and "z-index: 2" in current, current
    assert "inset 0 0 0 1.5px var(--tone)" in current, "the outline is the step's own colour"
    assert "width:" not in current and "flex:" not in current, current
    assert "transition: background .15s, transform .18s" in CSS
    assert ".step { transition: none; }" in CSS, "and it must hold still for reduced motion"

def test_the_current_step_shows_its_own_colour_so_the_highlight_shifts():
    """Outline, wash and number all read the step's tone, so stepping 1 -> 2 turns green into blue."""
    steps = CSS[CSS.index("/* ------------------------------------------------------- wizard steps"):]
    steps = steps[:steps.index("main {")] if "main {" in steps else steps
    assert 'color-mix(in srgb, var(--tone) 9%, var(--color-surface))' in steps
    assert "box-shadow: inset 0 0 0 1.5px var(--tone)" in steps
    assert "#16a34a" not in steps.lower(), "a hard-coded green would stop the highlight shifting colour"

def test_the_steps_and_the_cards_share_one_set_of_colours():
    """Defined once. Two copies of the same four tones is how two parts of one
    page drift into slightly different greens."""
    for tone in ("green", "blue", "orange", "purple"):
        assert _re.search(rf"^\.{tone}-card, \.tone-{tone} \{{", CSS, flags=_re.M), tone
        assert CSS.count(f".tone-{tone} {{") == 1


def test_the_step_bar_lines_up_with_the_page_beneath_it():
    rule = CSS[CSS.index(".steps {"):]
    rule = rule[:rule.index("}") + 1]
    assert "max-width: var(--content-max)" in rule and "margin-inline: auto" in rule, rule


def test_the_step_bar_gives_way_gracefully_when_narrow():
    """Five steps with icon tiles and one-line titles need ~1180px. Below that
    the tile goes; below 960px the row scrolls and the current step is kept in
    view. Measured: tile-less, the longest title fits down to ~930px and wraps by
    920, hence 960 and not the 860 this used to be."""
    assert "@media (max-width: 1180px) { .step-ico { display: none; } }" in CSS
    narrow = _media(960, ".steps-row")
    assert "overflow-x: auto" in narrow and "flex: 0 0 15.5rem" in narrow
    assert "row.scrollTo" in _RENDER and "row.scrollLeft = before" in _RENDER, (
        "a rebuilt row would otherwise snap back to the start on every step"
    )
    assert "prefers-reduced-motion: no-preference" in _RENDER


def test_the_current_step_is_recentred_when_the_window_changes_width():
    """The step has not changed, but where it sits has: a rotated phone, a
    resized window. Debounced, because dragging an edge fires dozens of events."""
    assert "function centreCurrentStep()" in APP
    assert 'addEventListener("resize"' in APP and "clearTimeout(resizeTimer)" in APP
    assert "setTimeout(centreCurrentStep, 120)" in APP


def test_a_hidden_tab_scrolls_instantly_because_smooth_scroll_never_runs_there():
    """Smooth scrolling is driven by animation frames, which a hidden tab does
    not run. The scroll silently never happened: scrollLeft stayed 0 while an
    instant scrollTo to the same target landed immediately."""
    centre = APP[APP.index("function centreCurrentStep()"):APP.index("let resizeTimer")]
    assert "!document.hidden" in centre
    assert "prefers-reduced-motion: no-preference" in centre


def test_finished_steps_get_a_check_and_the_copy_matches_the_design():
    """Done = before the current step AND its data exists, so skipping ahead past an empty step
    does not paint it as complete."""
    for line in ("How to run your program.", "What does it accept?", "Choose who writes inputs.",
                 "What counts as a failure?", "Review and launch."):
        assert line in APP, line
    done = APP[APP.index("function stepDone"):APP.index("function renderSteps")]
    assert "i < cur && stepDone(s.id)" in _RENDER
    for sid in ("sut", "grammar", "generators", "strategy"):
        assert f'id === "{sid}"' in done, sid
    assert 'id === "run"' not in done, "the last step is never 'done' before it is run"
    assert "step-ok" in _RENDER and "completed" in _RENDER, "the check needs a text alternative"
    assert _re.search(r"\.step-ok \{[^}]*background: var\(--color-primary\)", CSS)
    # text is centred against the tile, and boxes stay equal through flex bases rather than text height
    assert "align-items: center" in CSS[CSS.index(".step {"):CSS.index(".step:hover")]

def test_the_step_text_is_a_point_smaller_so_the_longest_title_has_room():
    """13.8px -> 12.5px for titles and 12.2px -> 11.5px for subtexts. At the old
    size 'System under test' needed 117px against a 112px column and wrapped; it
    now has room to spare. The subtext stays under the title, and above 11px."""
    title = CSS[CSS.index(".step .t {"):]
    title = title[:title.index("}") + 1]
    sub = CSS[CSS.index(".step .d {"):]
    sub = sub[:sub.index("}") + 1]
    t = float(title.split("font-size:")[1].split("rem")[0])
    d = float(sub.split("font-size:")[1].split("rem")[0])
    assert t == 0.78 and d == 0.72, (t, d)
    assert d < t, "the subtext must read as secondary"
    assert d * 16 >= 11, "below 11px it stops being legible"


def test_the_icon_tile_steps_aside_where_titles_would_otherwise_wrap():
    """At 1130px, with the tile showing, 'System under test' wrapped and the bar
    jumped from 79px to 95px. The tile now goes at the width the hero stacks."""
    assert "@media (max-width: 1180px) { .step-ico { display: none; } }" in CSS
    assert "@media (max-width: 1100px) { .step-ico" not in CSS


def test_the_row_scrolls_before_a_title_can_wrap():
    """Five tile-less steps hold one-line titles down to ~930px and wrap by 920,
    so the scroll takes over at 960 -- not the 860 it used to, which left a band
    where the bar was taller and one box had two lines of title."""
    narrow = _media(960, ".steps-row")
    assert "overflow-x: auto" in narrow
    assert "@media (max-width: 860px) {\n  .steps-row" not in CSS


def test_opening_from_the_spreadex_ui_link_lands_on_home():
    assert 'const FRESH_OPEN = !!incoming.searchParams.get("token");' in APP
    boot = APP[APP.index("(async function () {"):]
    assert 'FRESH_OPEN ? { tab: "landing" } : initialView(' in boot
    assert "!FRESH_OPEN && act.active" in boot


def test_light_is_the_shipped_theme_and_a_choice_is_kept_for_the_machine():
    assert 'var t = "light";' in INDEX and 'setAttribute("data-theme", t)' in INDEX
    assert 'api("/api/prefs", { theme: next })' in APP and "S.project.theme" in APP
