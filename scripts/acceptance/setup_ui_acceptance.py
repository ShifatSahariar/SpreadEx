"""Browser acceptance: the Workbench's setup wizard, driven the way a new user drives it.

Journey C, beside the CLI journeys in run_acceptance.py. It starts the installed `spreadex ui`
on a fresh, empty project (isolated SPREADEX_HOME) and, in a real Chromium, only clicks, types
and reads what is on screen:

  1. later steps are locked while step 1 is not done;
  2. each "How do you run your program?" card shows its own example (never Java for Python);
  3. a typo'd script is reported against the project folder, not a scratch folder, and
     Continue refuses a command whose test failed;
  4. the corrected command passes, Continue opens step 2, and steps 3-5 stay locked.

It also records, without judging, whether a project made by `spreadex init` opens with every
step unlocked (the gating rule for saved configs is an open decision).

Usage (SpreadEx and Playwright installed in the active environment):
    pip install playwright && python -m playwright install chromium
    python scripts/acceptance/setup_ui_acceptance.py --out acceptance-out
Exit status 0 only if every check passed; a report, screenshots and the server log go to --out.
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_acceptance import VALIDATOR, spreadex_exe  # noqa: E402

J = "setup-ui"


class Report:
    def __init__(self, out: Path) -> None:
        self.out, self.checks, self.notes = out, [], {}

    def check(self, name: str, ok: bool, detail: object = "") -> bool:
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
        self.log = log
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


def step_locked(page, n: int) -> bool:
    return page.locator(".steps-row button.step").nth(n - 1).is_disabled()


def open_setup(page, url: str) -> None:
    page.goto(url)
    page.locator("#tab-setup").click()
    page.locator("#sut-cmd").wait_for()


def wizard_journey(r: Report, page, url: str, project: Path, python: str) -> None:
    open_setup(page, url)

    # 1. Nothing after step 1 can be opened yet.
    r.check("a fresh project locks steps 2-5", all(step_locked(page, n) for n in range(2, 6)),
            [step_locked(page, n) for n in range(1, 6)])

    # 2. The example panel follows the card.
    example = page.locator(".ex-code code")
    expected = {"Script / Runtime": "python3 your_parser.py {input}",
                "Java / JVM": "java -jar rhino-all.jar {input}",
                "Executable": "./run-my-tool.sh {input}",
                "Custom command": "./run-my-tool.sh {input}"}
    for card, code in expected.items():
        page.get_by_role("radio", name=card).click()
        shown = example.inner_text().strip()
        r.check(f"the {card} card shows its own example", shown == code, shown)

    # 3. A typo in the script name.
    (project / "validate.py").write_text(VALIDATOR)
    page.get_by_role("radio", name="Script / Runtime").click()
    page.locator("#sut-cmd").fill(f"{python} valdiate.py {{input}}")
    page.locator("#sut-test").click()
    bad = page.locator(".res.bad")
    bad.wait_for(timeout=30000)
    text = bad.inner_text()
    page.screenshot(path=str(r.out / "setup-ui-typo.png"), full_page=True)
    r.check("a typo'd script is reported as not running", "It did not run" in text, text)
    r.check("the missing file is named against the project folder",
            "valdiate.py is not in the project folder" in text and str(project.name) in text, text)
    r.check("no scratch-folder path is shown", "spreadex-run-" not in text, text)
    page.get_by_role("button", name="Continue to Inputs").click()
    err = page.locator("#err").inner_text()
    r.check("Continue refuses a command whose test failed",
            "last Test connection failed" in err and step_locked(page, 2), err)

    # 4. The fix.
    page.locator("#sut-cmd").fill(f"{python} validate.py {{input}}")
    page.locator("#sut-test").click()
    good = page.locator(".res.good, .res.warn")
    good.wait_for(timeout=30000)
    text = good.inner_text()
    r.check("the corrected command is ready", "System ready!" in text, text)
    page.get_by_role("button", name="Continue to Inputs").click()
    page.locator(".steps-row button.step[aria-current='step']").wait_for()
    current = page.locator(".steps-row button.step[aria-current='step']").inner_text()
    page.screenshot(path=str(r.out / "setup-ui-step2.png"), full_page=True)
    r.check("Continue opens step 2", "Inputs" in current, current)
    r.check("steps 3-5 stay locked until step 2 is done",
            all(step_locked(page, n) for n in (3, 4, 5)), [step_locked(page, n) for n in range(1, 6)])


def init_observation(r: Report, exe: str, browser, work: Path, env: dict, python: str) -> None:
    """Recorded, not judged: whether an `init` project opens with every step unlocked."""
    project = work / "from-init"
    subprocess.run([exe, "init", str(project), "--command", python, "validate.py", "{input}",
                    "--grammar", "g.bnf"], cwd=work, env=env, capture_output=True, text=True, timeout=120)
    if not (project / "spreadex.yaml").is_file():
        r.notes["init_project_steps_unlocked"] = "init did not write spreadex.yaml"
        return
    ui = Workbench(exe, project, env, r.out / "setup-ui-init-server.log")
    try:
        page = browser.new_page()
        open_setup(page, ui.url)
        r.notes["init_project_steps_unlocked"] = [not step_locked(page, n) for n in range(1, 6)]
        page.close()
    finally:
        ui.stop()


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
        home, work = tmp / "home", tmp / "work"
        project = work / "my-json-validator"
        for d in (home, project):
            d.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k not in ("SPREADEX_HOST_GENERATORS", "PYTHONPATH")}
        env.update(SPREADEX_HOME=str(home), SPREADEX_CACHE=str(tmp / "cache"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            ui = Workbench(exe, project, env, out / "setup-ui-server.log")
            page = browser.new_page()
            page.on("pageerror", lambda e: r.notes.setdefault("page_errors", []).append(str(e)))
            try:
                wizard_journey(r, page, ui.url, project, python)
            except Exception as exc:                       # a timeout is a failure, with a picture
                r.check("the journey completes", False, f"{type(exc).__name__}: {exc}")
                page.screenshot(path=str(out / "setup-ui-failure.png"), full_page=True)
            finally:
                ui.stop()
            r.check("no JavaScript errors on the page", not r.notes.get("page_errors"), r.notes.get("page_errors"))
            init_observation(r, exe, browser, work, env, python)
            browser.close()
    r.write()
    print(f"  note: steps unlocked in an init project: {r.notes.get('init_project_steps_unlocked')}")
    print(f"\nreport: {out / 'setup-ui-report.json'}")
    print("SETUP UI ACCEPTANCE " + ("PASSED" if r.ok() else "FAILED"))
    return 0 if r.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
