"""Browser acceptance: the Workbench's setup wizard, driven the way a user drives it.

Journey C, beside the CLI journeys in run_acceptance.py. Each scenario starts the installed
`spreadex ui` on its own project (isolated SPREADEX_HOME) and, in a fresh browser context of a
real Chromium, only clicks, types and reads what is on screen:

  fresh      an empty folder: steps 2-5 locked; the command box is empty, each card's example is
             only its grey placeholder; Test with an empty box says so without running anything;
             each "How do you run your program?" card shows its own example; a typo'd script is named against the project folder; Continue is
             refused after a failed test; the fix opens step 2 and keeps 3-5 locked.
  init       a project made by `spreadex init`: opens at step 1 with the command prefilled (and
             kept when another card is picked) and steps 2-5 locked.
  example    from a fresh project and from a configured one with history: Start from an example ->
             Rhino opens a SEPARATE Workbench at step 1, command prefilled and untested, later steps
             locked; the user's project is byte-for-byte untouched; Inputs shows the grammar per
             generator; Generators shows FuzzingBook not recommended and Fuzz4All replaying a
             recording; the file Review & run would write keeps every example setting.
  guides     Help & Guides from the menu: seven sections with their screenshots, contextual Guide
             links from a step and from a failed Test connection, example tabs, collapsed advanced
             sections, the CLI reference from the parser, a phone-sized layout and dark theme.
  no-config  campaign history whose spreadex.yaml is then deleted while the Workbench is open:
             step 1 again, empty command, later steps locked, the old campaigns still listed,
             and the server refuses to launch from its stale state.
  history    projects whose campaign ran from the CLI -- one finished, one stopped mid-run --
             allow every step, mark none done, and do not count the campaign as a tested
             connection: Launch waits for a Test connection.
  returning  a successful test is remembered by this browser and shown as "verified earlier";
             editing the command in the wizard marks the test stale and Continue refuses it;
             a command changed in spreadex.yaml invalidates the remembered test.

The CLI is never gated by the wizard: the history projects' campaigns are run with
`spreadex run` before the Workbench has ever opened them.

Usage (SpreadEx and Playwright installed in the active environment):
    pip install playwright && python -m playwright install chromium
    python scripts/acceptance/setup_ui_acceptance.py --out acceptance-out
Exit status 0 only if every check passed; a report, screenshots and server logs go to --out.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_acceptance import VALIDATOR, spreadex_exe  # noqa: E402

J = "setup-ui"
SLOW_VALIDATOR = "import time\ntime.sleep(1.5)\n" + VALIDATOR


class Report:
    def __init__(self, out: Path) -> None:
        self.out, self.checks, self.notes = out, [], {}
        self.scenario = ""

    def check(self, name: str, ok: bool, detail: object = "") -> bool:
        name = f"{self.scenario}: {name}"
        self.checks.append({"journey": J, "check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))
        return bool(ok)

    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def write(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "setup-ui-report.json").write_text(json.dumps({
            "platform": platform.platform(), "python": sys.version.split()[0],
            "passed": self.ok(), "notes": self.notes, "checks": self.checks}, indent=1))


class Workbench:
    """`spreadex ui` for one project, stopped on exit."""

    def __init__(self, exe: str, project: Path, env: dict, log: Path) -> None:
        self.fh = open(log, "w")
        self.proc = subprocess.Popen([exe, "ui", "--no-open"], cwd=project, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.url = None
        deadline = time.time() + 60
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.fh.write(line)
            m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", line)
            if m:
                self.url = m.group(1)
                break
        if not self.url:
            self.stop()
            raise RuntimeError(f"the Workbench did not print its address; see {log}")

    def _request(self, route: str, body: dict | None = None) -> dict:
        u = urlparse(self.url)
        headers = {"X-SpreadEx-Token": parse_qs(u.query)["token"][0]}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"{u.scheme}://{u.netloc}{route}", data=data, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:          # a refusal is an answer, not a crash
            return {"ok": False, "status": exc.code, "error": exc.read().decode(errors="replace")}

    def get(self, route: str) -> dict:
        return self._request(route)

    def post(self, route: str, body: dict) -> dict:
        return self._request(route, body)

    def runs(self) -> list[dict]:
        return self.get("/api/runs")["runs"]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        rest = self.proc.stdout.read() if self.proc.stdout else ""
        self.fh.write(rest or "")
        self.fh.close()


# ------------------------------------------------------------------- page helpers

def steps(page) -> list[bool]:
    """Which of the five steps can be opened."""
    buttons = page.locator(".steps-row button.step")
    return [not buttons.nth(i).is_disabled() for i in range(5)]


def done_marks(page) -> int:
    return page.locator(".steps-row .step-item.done").count()


def current_step(page) -> str:
    return page.locator(".steps-row button.step[aria-current='step']").inner_text()


def open_setup(page, url: str) -> None:
    page.goto(url)
    page.locator("#tab-setup").click()
    page.locator(".steps-row button.step").first.wait_for()


def goto_step(page, n: int) -> None:
    page.locator(".steps-row button.step").nth(n - 1).click()


def test_connection(page) -> str:
    """Click Test connection and wait for this test's outcome, not whatever was shown before."""
    page.locator("#sut-test").click()
    # Synchronise on the page's own record of this test (finished, for the settings on screen);
    # every assertion is then made on the visible text.
    page.wait_for_function("() => S.probe && !S.probe.pending && S.probe.key === draftSutKey()", timeout=30000)
    return page.locator("#probe").inner_text()


def launch_enabled(page) -> bool:
    goto_step(page, 5)
    page.locator("#launch").wait_for()
    return page.locator("#launch").is_enabled()


def ready_why(page) -> str:
    why = page.locator(".ready-why")
    return why.inner_text() if why.count() else ""


# ---------------------------------------------------------------- project helpers

def init_project(exe: str, folder: Path, env: dict, python: str, validator: str = VALIDATOR,
                 corpus: bool = False) -> Path:
    """`spreadex init`, as a user would; with `corpus`, seeds replace generators so that
    `spreadex run` needs nothing installed."""
    subprocess.run([exe, "init", str(folder), "--command", python, "validate.py", "{input}",
                    "--grammar", "json.bnf"], cwd=folder.parent, env=env, capture_output=True,
                   text=True, timeout=120, check=True)
    (folder / "validate.py").write_text(validator)
    if corpus:
        seeds = folder / "seeds"
        seeds.mkdir()
        for i, text in enumerate(["[1, 2]", '{"a": 1}', "[1] 2", "1 2", "true", "[]"]):
            (seeds / f"s{i}.json").write_text(text)
        cfg = yaml.safe_load((folder / "spreadex.yaml").read_text())
        cfg["generators"] = []
        cfg["corpus"] = {"path": "seeds"}
        cfg.pop("grammar", None)
        (folder / "spreadex.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    return folder


# ---------------------------------------------------------------------- scenarios

def fresh(r: Report, page, project: Path, python: str) -> None:
    r.check("steps 2-5 are locked", steps(page) == [True, False, False, False, False], steps(page))

    box = page.locator("#sut-cmd")
    page.get_by_role("radio", name="Script / Runtime").click()
    r.check("the command box is empty; the example is only a placeholder",
            box.input_value() == "" and box.get_attribute("placeholder") == "python3 your_parser.py {input}",
            [box.input_value(), box.get_attribute("placeholder")])
    page.get_by_role("radio", name="Java / JVM").click()
    r.check("another card changes only the placeholder",
            box.input_value() == "" and box.get_attribute("placeholder") == "java -jar your-tool.jar {input}",
            [box.input_value(), box.get_attribute("placeholder")])
    probes: list[str] = []
    page.on("request", lambda req: probes.append(req.url) if "/api/probe" in req.url else None)
    page.locator("#sut-test").click()
    page.wait_for_timeout(500)
    err = page.locator("#err").inner_text()
    r.check("Test with an empty command explains what is missing",
            "Enter the command that runs your program" in err, err)
    r.check("an empty command starts nothing", not probes and "It did not run" not in page.locator("#probe").inner_text(),
            probes)

    example = page.locator(".ex-code code")
    expected = {"Script / Runtime": "python3 your_parser.py {input}",
                "Java / JVM": "java -jar rhino-all.jar {input}",
                "Executable": "./run-my-tool.sh {input}",
                "Custom command": "./run-my-tool.sh {input}"}
    for card, code in expected.items():
        page.get_by_role("radio", name=card).click()
        shown = example.inner_text().strip()
        r.check(f"the {card} card shows its own example", shown == code, shown)

    (project / "validate.py").write_text(VALIDATOR)
    page.get_by_role("radio", name="Script / Runtime").click()
    page.locator("#sut-cmd").fill(f"{python} valdiate.py {{input}}")
    text = test_connection(page)
    page.screenshot(path=str(r.out / "setup-ui-fresh-typo.png"), full_page=True)
    r.check("a typo'd script is reported as not running", "It did not run" in text, text)
    r.check("the missing file is named against the project folder",
            "valdiate.py is not in the project folder" in text and project.name in text, text)
    r.check("no scratch-folder path is shown", "spreadex-run-" not in text, text)
    page.get_by_role("button", name="Continue to Inputs").click()
    err = page.locator("#err").inner_text()
    r.check("Continue refuses a command whose test failed",
            "last Test connection failed" in err and not steps(page)[1], err)

    page.locator("#sut-cmd").fill(f"{python} validate.py {{input}}")
    text = test_connection(page)
    r.check("the corrected command is ready", "System ready!" in text, text)
    page.get_by_role("button", name="Continue to Inputs").click()
    page.locator(".steps-row button.step[aria-current='step']").wait_for()
    r.check("Continue opens step 2", "Inputs" in current_step(page), current_step(page))
    r.check("steps 3-5 stay locked until step 2 is done",
            steps(page) == [True, True, False, False, False], steps(page))


def from_init(r: Report, page, python: str) -> None:
    r.check("opens at step 1", "System under test" in current_step(page), current_step(page))
    value = page.locator("#sut-cmd").input_value()
    r.check("the init command is prefilled", value == f"{python} validate.py {{input}}", value)
    page.get_by_role("radio", name="Java / JVM").click()
    kept = page.locator("#sut-cmd").input_value()
    r.check("picking another card keeps the saved command", kept == value, kept)
    r.check("steps 2-5 are locked", steps(page) == [True, False, False, False, False], steps(page))
    r.check("no step is marked done", done_marks(page) == 0, done_marks(page))


def with_history(r: Report, page) -> None:
    r.check("every step can be opened", steps(page) == [True] * 5, steps(page))
    r.check("history marks no step done", done_marks(page) == 0, done_marks(page))
    r.check("history is not a tested connection: Launch waits", not launch_enabled(page), ready_why(page))
    r.check("Review & run says why", "has not been tested in this browser" in ready_why(page), ready_why(page))
    goto_step(page, 1)
    text = test_connection(page)
    r.check("Test connection passes", "System ready!" in text, text)
    r.check("after a real test, Launch is available", launch_enabled(page), ready_why(page))


def returning(r: Report, page, url: str, project: Path, python: str) -> None:
    goto_step(page, 1)
    text = test_connection(page)
    r.check("Test connection passes", "System ready!" in text, text)

    # The same browser comes back: the test is remembered, and labelled as such.
    open_setup(page, url)
    goto_step(page, 1)
    note = page.locator("#probe").inner_text()
    r.check("the remembered test is shown as verified earlier, not as a fresh test",
            "Verified earlier in this browser" in note and "System ready!" not in note, note)
    r.check("an unchanged command can launch without re-testing", launch_enabled(page), ready_why(page))
    items = page.locator(".ready-list").inner_text()
    r.check("Review & run labels it verified earlier", "SUT (verified earlier)" in items, items)

    # Editing in the wizard: the shown result goes stale and Continue will not accept it.
    goto_step(page, 1)
    page.locator("#sut-cmd").fill(f"{python} -u validate.py {{input}}")
    stale = page.locator("#probe").inner_text()
    r.check("an edited command marks the previous test stale", "Settings changed since the last test" in stale, stale)
    page.get_by_role("button", name="Continue to Inputs").click()
    err = page.locator("#err").inner_text()
    r.check("Continue refuses the edited command until it is tested", "Test the connection first" in err, err)
    page.screenshot(path=str(r.out / "setup-ui-returning-stale.png"), full_page=True)

    # Changed on disk: the remembered test no longer applies.
    cfg = yaml.safe_load((project / "spreadex.yaml").read_text())
    cfg["sut"]["timeout"] = "7s"
    (project / "spreadex.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    open_setup(page, url)
    r.check("a changed execution setting invalidates the remembered test", not launch_enabled(page), ready_why(page))
    r.check("Review & run says the settings changed", "changed since they were last tested" in ready_why(page),
            ready_why(page))
    goto_step(page, 1)
    r.check("step 1 no longer claims an earlier verification",
            "Verified earlier" not in page.locator("#probe").inner_text(), page.locator("#probe").inner_text())
    text = test_connection(page)
    r.check("a new successful test makes it launchable again", "System ready!" in text and launch_enabled(page),
            ready_why(page))


def no_config(r: Report, page, ui: "Workbench", project: Path) -> None:
    r.check("with spreadex.yaml present, history allows every step", steps(page) == [True] * 5, steps(page))
    (project / "spreadex.yaml").unlink()
    open_setup(page, ui.url)
    r.check("without spreadex.yaml: step 1 again", "System under test" in current_step(page), current_step(page))
    r.check("without spreadex.yaml: later steps locked despite history",
            steps(page) == [True, False, False, False, False], steps(page))
    box = page.locator("#sut-cmd")
    r.check("without spreadex.yaml: the command box is empty", box.input_value() == "", box.input_value())
    runs = ui.runs()
    r.check("the old campaign is kept and still listed", len(runs) == 1 and (project / ".spreadex" / "runs").is_dir(),
            runs)
    page.locator("#tab-results").click()
    page.wait_for_timeout(800)
    shown = page.locator("#view").inner_text()
    r.check("Campaigns still shows it, not the empty state", "No campaigns yet" not in shown and shown.strip(),
            shown[:300])
    started = ui.post("/api/run", {"jobs": 1})
    r.check("the server refuses to launch without spreadex.yaml",
            started.get("ok") is False and "spreadex.yaml" in str(started.get("error")), started)
    (project / "spreadex.yaml").write_text("sut: [unclosed\n")
    info = ui.get("/api/project")
    started = ui.post("/api/run", {"jobs": 1})
    r.check("a spreadex.yaml that does not parse is not configured and cannot launch",
            info.get("configured") is False and started.get("ok") is False, [info.get("config_error"), started])
    open_setup(page, ui.url)
    r.check("with an invalid spreadex.yaml, later steps stay locked",
            steps(page) == [True, False, False, False, False], steps(page))


# --------------------------------------------------------------------------- main

def cli_run(r: Report, exe: str, project: Path, env: dict) -> None:
    out = subprocess.run([exe, "run"], cwd=project, env=env, capture_output=True, text=True, timeout=600)
    r.check("`spreadex run` works without the Workbench", out.returncode == 0, (out.stdout + out.stderr)[-600:])


def stopped_cli_run(r: Report, exe: str, project: Path, env: dict, ui: Workbench) -> None:
    """A campaign stopped mid-run, and only then the browser: once /api/runs returns it stopped."""
    proc = subprocess.Popen([exe, "run"], cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline, seen = time.time() + 120, None
    while time.time() < deadline and not seen:
        seen = next(iter(ui.runs()), None)
        if not seen:
            time.sleep(0.5)
    proc.terminate()
    proc.wait(30)
    status = None
    while time.time() < deadline:
        runs = ui.runs()
        status = runs[0]["status"] if runs else None
        if status and status not in ("running",):
            break
        time.sleep(0.5)
    r.notes["stopped_run_status"] = status
    r.check("the stopped campaign is recorded and returned by /api/runs",
            status in ("aborted", "cancelled", "failed"), status)


def snapshot(folder: Path) -> dict:
    """Every file under a folder and its bytes' hash: to prove the folder was not touched."""
    import hashlib
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "ui-token"}


def click_text(page, text: str) -> None:
    page.get_by_role("button", name=text).first.click()


def example(r: Report, page, project: Path) -> None:
    before = snapshot(project)
    goto_step(page, 1)
    page.locator("[data-start='example']").click()
    page.locator("[data-example='rhino'] .primary").wait_for()
    page.locator("[data-example='rhino'] .primary").click()
    page.wait_for_function("() => document.querySelector('.demo-tag') && /Example: Rhino/.test(document.querySelector('.demo-tag').textContent)",
                           timeout=60000)
    page.locator("#sut-cmd").wait_for()
    r.check("the example opens in its own Workbench", "Example: Rhino" in page.locator(".demo-tag").inner_text())
    r.check("it opens at step 1", "System under test" in current_step(page), current_step(page))
    cmd = page.locator("#sut-cmd").input_value()
    r.check("the Rhino command is prefilled", "${SPREADEX_RUNTIME_RHINO}" in cmd and "tools.shell.Main" in cmd, cmd)
    r.check("it is not treated as tested: later steps locked", steps(page) == [True, False, False, False, False], steps(page))
    r.check("no test result is shown before testing", "System ready!" not in page.locator("#probe").inner_text())
    r.check("the user's project is untouched", snapshot(project) == before,
            sorted(set(snapshot(project)) ^ set(before)))

    text = test_connection(page)
    r.check("Test connection passes on the pinned Rhino", "System ready!" in text, text)
    click_text(page, "Continue to Inputs")
    page.locator(".prep-table").wait_for()
    table = page.locator(".prep-table").inner_text()
    r.check("Inputs shows a grammar for each generator", "rhino.fan" in table and "rhino.g4" in table, table)
    r.check("Inputs says Fuzz4All replays a recorded corpus",
            "replays a recorded corpus" in page.locator("main").inner_text())
    click_text(page, "Continue to Generators")
    page.locator("[data-gen='fuzzingbook']").wait_for()
    fb = page.locator("[data-gen='fuzzingbook']").inner_text()
    r.check("FuzzingBook is marked not recommended, with the reason", "Not recommended for this example" in fb, fb)
    f4a = page.locator("[data-gen='fuzz4all']").inner_text()
    r.check("Fuzz4All is labelled as replaying a recording", "Replays a recording" in f4a, f4a)
    click_text(page, "Continue to Testing strategy")
    click_text(page, "Continue to Review & run")
    page.locator("#preview").wait_for(state="attached")
    y = page.locator("#preview").text_content()
    r.check("the file Review & run would write keeps every example setting",
            '"mode":"recorded"' in y and "rhino.fan" in y and "rhino.g4" in y and "presets:" in y
            and "${SPREADEX_RUNTIME_RHINO}" in y, y[-600:])
    notice = re.search(r"Installed on first run:[^\n]*", page.locator("main").inner_text())
    r.check("no false install notice for a replayed generator",
            not notice or "Fuzz4All" not in notice.group(0), notice.group(0) if notice else "")
    r.check("the user's project is still untouched", snapshot(project) == before)


GUIDE_SECTIONS = ["sut", "inputs", "generators", "strategy", "run", "results", "troubleshooting"]


def guides(r: Report, page, project: Path, python: str) -> None:
    page.locator("#tab-guides").click()
    page.locator(".g-body h1").wait_for()
    r.check("the Guides menu entry opens the guides", page.locator("#tab-guides").get_attribute("aria-selected") == "true"
            and "System under test" in page.locator(".g-body h1").inner_text())
    broken = []
    for sec in GUIDE_SECTIONS:
        page.locator(f"[data-guide='{sec}']").click()
        page.locator(f"[data-guide-section='{sec}']").wait_for()
        for img in page.locator(".g-fig img").all():
            img.scroll_into_view_if_needed()
            if not page.evaluate("(i) => i.complete && i.naturalWidth > 0", img.element_handle()):
                broken.append((sec, img.get_attribute("src")))
    r.check("all seven sections render, every screenshot loads", not broken, broken)

    page.locator("[data-guide='troubleshooting']").click()
    page.locator(".g-cmd").first.wait_for()
    r.check("the CLI reference is generated", page.locator(".g-cmd").count() >= 10
            and "spreadex runtimes" in page.locator("#g-cli").inner_text())

    page.locator("[data-guide='sut']").click()
    page.locator(".g-tabs").first.wait_for()
    tabs = page.locator(".g-tabs").first
    tabs.locator(".g-tabbar button").nth(1).click()
    r.check("example tabs switch", tabs.locator(".g-tabpane").nth(1).is_visible()
            and not tabs.locator(".g-tabpane").nth(0).is_visible())
    r.check("advanced sections start collapsed",
            page.locator("details.g-adv").count() > 0 and page.evaluate("() => [...document.querySelectorAll('details.g-adv')].every(d => !d.open)"))

    # Contextual links: from a step title, and from a failed Test connection.
    page.locator("#tab-setup").click()
    page.locator("#sut-cmd").fill(f"{python} missing_script.py {{input}}")
    test_connection(page)
    page.get_by_role("button", name="How to fix this").click()
    page.locator("[data-guide-section='sut']").wait_for()
    page.wait_for_timeout(400)
    in_view = page.evaluate("() => { const r = document.getElementById('g-common-problems').getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }")
    r.check("a failed Test connection links to its guide section", in_view)
    page.locator("#tab-setup").click()
    page.locator(".sut-head .guide-link").first.click()
    page.locator("[data-guide-section='sut']").wait_for()
    r.check("a step's Guide link opens the matching section", page.locator("[data-guide-section='sut']").count() == 1)

    # A phone: the section picker replaces the list, and nothing scrolls sideways.
    page.set_viewport_size({"width": 375, "height": 812})
    page.locator(".g-pick select").select_option("generators")
    page.locator("[data-guide-section='generators']").wait_for()
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    menu = page.evaluate("() => { const t = document.querySelector('.tabs'); return t.scrollWidth - t.clientWidth; }")
    r.check("on a phone: the picker works, no sideways scrolling, the whole menu fits", overflow <= 0 and menu <= 0,
            {"page_overflow": overflow, "menu_overflow": menu})
    page.set_viewport_size({"width": 1280, "height": 900})

    # Dark theme: callout text stays readable on its background.
    page.evaluate("() => applyTheme('dark')")
    page.locator("[data-guide='generators']").click()
    page.locator(".g-call").first.wait_for()
    ratios = page.evaluate("""() => [...document.querySelectorAll('.g-call, .g-prob-s, .g-prob-fix')].slice(0, 6).map(el => {
      const rgb = c => (c.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(Number);
      const lum = c => { const v = rgb(c).map(x => { x /= 255; return x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; });
        return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
      let bg = getComputedStyle(el).backgroundColor, n = el;
      while (/rgba\(0, 0, 0, 0\)|transparent/.test(bg) && n.parentElement) { n = n.parentElement; bg = getComputedStyle(n).backgroundColor; }
      const fg = getComputedStyle(el.querySelector('p, span, strong') || el).color;
      const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x); return (a + .05) / (b + .05); })""")
    page.evaluate("() => applyTheme('light')")
    r.check("dark theme: callouts keep readable contrast (4.5:1)", ratios and min(ratios) >= 4.5, ratios)


def scenario(r: Report, browser, name: str, exe: str, project: Path, env: dict, body, before=None) -> None:
    r.scenario = name
    print(f"\n  -- {name}")
    ui = Workbench(exe, project, env, r.out / f"setup-ui-{name}-server.log")
    ctx = browser.new_context()
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        if before:
            before(ui)
        open_setup(page, ui.url)
        body(page, ui)
    except Exception as exc:                               # a timeout is a failure, with a picture
        r.check("the scenario completes", False, f"{type(exc).__name__}: {exc}")
        page.screenshot(path=str(r.out / f"setup-ui-{name}-failure.png"), full_page=True)
    finally:
        ui.stop()
        ctx.close()
    r.check("no JavaScript errors on the page", not errors, errors)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="acceptance-out")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    args = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright is not installed: pip install playwright && python -m playwright install chromium")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    r = Report(out)
    exe = spreadex_exe()
    # What a user would type: `python` where it exists (Windows, venvs), else `python3`.
    python = "python" if shutil.which("python") else "python3"
    print(f"\nC. setup wizard in a browser ({python!r} as the interpreter)")
    with tempfile.TemporaryDirectory(prefix="spreadex-setup-ui-") as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("SPREADEX_HOST_GENERATORS", "PYTHONPATH")}
        env.update(SPREADEX_HOME=str(tmp / "home"), SPREADEX_CACHE=str(tmp / "cache"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)

            p = work / "fresh"
            p.mkdir()
            scenario(r, browser, "fresh", exe, p, env, lambda page, ui: fresh(r, page, p, python))

            p_init = init_project(exe, work / "from-init", env, python)
            scenario(r, browser, "init", exe, p_init, env, lambda page, ui: from_init(r, page, python))

            r.scenario = "history-finished"
            p_done = init_project(exe, work / "finished", env, python, corpus=True)
            cli_run(r, exe, p_done, env)
            scenario(r, browser, "history-finished", exe, p_done, env, lambda page, ui: with_history(r, page))

            p_stop = init_project(exe, work / "stopped", env, python, validator=SLOW_VALIDATOR, corpus=True)
            scenario(r, browser, "history-stopped", exe, p_stop, env, lambda page, ui: with_history(r, page),
                     before=lambda ui: stopped_cli_run(r, exe, p_stop, env, ui))

            p_gone = init_project(exe, work / "no-config", env, python, corpus=True)
            r.scenario = "no-config"
            cli_run(r, exe, p_gone, env)
            scenario(r, browser, "no-config", exe, p_gone, env, lambda page, ui: no_config(r, page, ui, p_gone))

            p_g = work / "guides"
            p_g.mkdir()
            scenario(r, browser, "guides", exe, p_g, env, lambda page, ui: guides(r, page, p_g, python))

            p_ex = work / "example-from-fresh"
            p_ex.mkdir()
            scenario(r, browser, "example-from-fresh", exe, p_ex, env, lambda page, ui: example(r, page, p_ex))
            p_ex2 = init_project(exe, work / "example-from-configured", env, python, corpus=True)
            r.scenario = "example-from-configured"
            cli_run(r, exe, p_ex2, env)
            scenario(r, browser, "example-from-configured", exe, p_ex2, env, lambda page, ui: example(r, page, p_ex2))

            p_back = init_project(exe, work / "returning", env, python, corpus=True)
            r.scenario = "returning"
            cli_run(r, exe, p_back, env)
            scenario(r, browser, "returning", exe, p_back, env,
                     lambda page, ui: returning(r, page, ui.url, p_back, python))
            browser.close()
    r.write()
    print(f"\nreport: {out / 'setup-ui-report.json'}")
    print("SETUP UI ACCEPTANCE " + ("PASSED" if r.ok() else "FAILED"))
    return 0 if r.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
