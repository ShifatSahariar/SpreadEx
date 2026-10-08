"""Capture the Guides' screenshots from the real Workbench, annotated, into the package.

    pip install playwright && python -m playwright install chromium
    python scripts/docs/capture_guides.py            # all screenshots
    python scripts/docs/capture_guides.py run-ready  # just these ids

What is captured is described by src/spreadex/api/static/guides/screenshots.json:

    "<id>": {"project": "fresh" | "own" | "rhino",   which throw-away project to show
             "screen": "<name>",                     where to navigate (SCREENS below)
             "caption": "...",                       shown under the image
             "marks": [{"selector": "...", "label": "..."}]}   numbered markers, in order

Each project is a neutral temporary folder; a fresh SPREADEX_HOME is used, and a capture is
refused if the page shows any local path. Light theme, 1280 px wide. The Rhino project is
prepared with `spreadex example rhino` and one real `spreadex run` (generators and the pinned
runtime come from the normal SpreadEx cache, installed if missing). Re-run after a UI change;
tests/test_guides.py checks that ids, files and selectors still agree.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "src" / "spreadex" / "api" / "static" / "guides"
IMG = GUIDES / "img"
WIDTH, MAX_HEIGHT = 1280, 1100

VALIDATOR = '''import json, sys
try:
    json.loads(open(sys.argv[1]).read())
except json.JSONDecodeError as e:
    print(f"invalid: {e}", file=sys.stderr)
    sys.exit(2)
print("ok")
'''


def spreadex() -> str:
    exe = Path(sys.executable).parent / ("spreadex.exe" if os.name == "nt" else "spreadex")
    return str(exe) if exe.exists() else (shutil.which("spreadex") or sys.exit("spreadex is not installed"))


class Workbench:
    def __init__(self, project: Path, env: dict) -> None:
        self.proc = subprocess.Popen([spreadex(), "ui", "--no-open"], cwd=project, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.url = None
        end = time.time() + 60
        while time.time() < end and not self.url:
            m = re.search(r"(http://127\.0\.0\.1:\d+/\?token=\S+)", self.proc.stdout.readline())
            self.url = m and m.group(1)
        if not self.url:
            raise RuntimeError("the Workbench did not start")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(10)


# ------------------------------------------------------------------- navigation

def click(page, text: str) -> None:
    page.get_by_role("button", name=text).first.click()


def setup(page) -> None:
    page.locator("#tab-setup").click()
    page.locator(".steps-row button.step").first.wait_for()


def step(page, n: int) -> None:
    page.locator(".steps-row button.step").nth(n - 1).click()
    page.wait_for_timeout(1500)


def test_connection(page) -> None:
    page.locator("#sut-test").click()
    page.wait_for_function("() => /System ready!|It did not run|No answer in time/.test(document.querySelector('#probe').textContent)",
                           timeout=30000)


def fill_if_empty(page) -> None:
    """A new custom project has no command yet: type the one the guides use."""
    if not page.locator("#sut-cmd").input_value():
        page.locator("#sut-cmd").fill("python validate.py {input}")


def open_run(page) -> None:
    page.locator("#tab-results").click()
    page.wait_for_timeout(1200)
    page.evaluate("() => { pickRun(S.runs[0].run_id); }")
    page.wait_for_timeout(1500)


def run_tab(page, tab: str) -> None:
    page.evaluate(f"() => {{ pickResultTab('{tab}'); }}")
    page.wait_for_timeout(1500)


SCREENS = {
    "step1": lambda p: setup(p),
    "step1-examples": lambda p: (setup(p), p.locator("[data-start='example']").click(), p.locator("[data-example='rhino']").wait_for()),
    "step1-tested": lambda p: (setup(p), p.locator("#sut-cmd").fill("python validate.py {input}"), test_connection(p)),
    "step2": lambda p: (setup(p), fill_if_empty(p), test_connection(p), click(p, "Continue to Inputs"), p.wait_for_timeout(2500)),
    "step3": lambda p: (setup(p), step(p, 3)),
    "step4": lambda p: (setup(p), step(p, 4)),
    "step5": lambda p: (setup(p), step(p, 5)),
    "step5-ready": lambda p: (setup(p), test_connection(p), step(p, 5)),
    "campaigns": lambda p: (p.locator("#tab-results").click(), p.wait_for_timeout(1500),
                            p.evaluate("() => { S.rview = 'list'; renderResults(); }"), p.wait_for_timeout(800)),
    "run-generators": lambda p: (open_run(p), run_tab(p, "generators")),
    "run-findings": lambda p: (open_run(p), run_tab(p, "findings")),
}

NEUTRAL_JS = """(roots) => {
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const fix = t => roots.reduce((acc, r) => acc.split(r).join('~/projects'), t);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) if (roots.some(r => n.nodeValue.includes(r))) n.nodeValue = fix(n.nodeValue);
  document.querySelectorAll('input, textarea').forEach(i => { if (roots.some(r => i.value.includes(r))) i.value = fix(i.value); });
}"""

MARK_JS = """(marks) => {
  document.querySelectorAll('.cap-mark').forEach(n => n.remove());
  let top = Infinity, bottom = 0;
  marks.forEach((m, i) => {
    const el = document.querySelector(m.selector);
    if (!el) throw new Error('missing element for mark: ' + m.selector);
    const r = el.getBoundingClientRect(), x = r.left + scrollX, y = r.top + scrollY;
    top = Math.min(top, y); bottom = Math.max(bottom, y + r.height);
    const box = document.createElement('div');
    box.className = 'cap-mark';
    Object.assign(box.style, {position: 'absolute', left: (x - 3) + 'px', top: (y - 3) + 'px', width: (r.width + 6) + 'px',
      height: (r.height + 6) + 'px', border: '2px solid #f59e0b', borderRadius: '8px', zIndex: 9998, pointerEvents: 'none'});
    const n = document.createElement('div');
    n.className = 'cap-mark'; n.textContent = String(i + 1);
    Object.assign(n.style, {position: 'absolute', left: (x - 12) + 'px', top: (y - 12) + 'px', width: '24px', height: '24px',
      borderRadius: '50%', background: '#f59e0b', color: '#111', font: '700 13px system-ui', display: 'grid',
      placeItems: 'center', zIndex: 9999, boxShadow: '0 1px 3px rgba(0,0,0,.3)', pointerEvents: 'none'});
    document.body.append(box, n);
  });
  return marks.length ? [top, bottom] : null;
}"""


def capture(page, shot_id: str, spec: dict, forbidden: list[str]) -> None:
    SCREENS[spec["screen"]](page)
    page.wait_for_timeout(600)
    # The throw-away projects live in a temporary folder; show it as a neutral ~/projects, the way a
    # reader's own path would appear, instead of this machine's temporary directory.
    page.evaluate(NEUTRAL_JS, [p for p in forbidden[:1] if p] + [os.path.realpath(forbidden[0])])
    text = page.evaluate("() => document.body.innerText")
    leaked = [f for f in forbidden if f and f in text]
    if leaked:
        raise RuntimeError(f"{shot_id}: the page shows a local path ({leaked[0]}); not capturing it")
    span = page.evaluate(MARK_JS, spec.get("marks") or [])
    view_top = page.evaluate("() => document.querySelector('main#view').getBoundingClientRect().top + scrollY")
    top = max(0, (span[0] - 60) if span else view_top - 10)
    top = min(top, view_top - 10) if span and span[1] - view_top < MAX_HEIGHT else top
    height = page.evaluate("() => document.documentElement.scrollHeight")
    clip = {"x": 0, "y": top, "width": WIDTH, "height": min(MAX_HEIGHT, height - top)}
    IMG.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(IMG / f"{shot_id}.png"), full_page=True, clip=clip)
    page.evaluate("() => document.querySelectorAll('.cap-mark').forEach(n => n.remove())")
    print(f"  {shot_id}.png")


def prepare(kind: str, base: Path, env: dict) -> Path:
    project = base / {"fresh": "my-project", "own": "json-validator", "rhino": "rhino-example"}[kind]
    if kind == "rhino":
        subprocess.run([spreadex(), "runtimes", "install", "rhino"], env=env, check=True)
        subprocess.run([spreadex(), "generators", "install", "fandango", "grammarinator"], env=env, check=True)
        subprocess.run([spreadex(), "example", "rhino", str(project)], env=env, check=True, capture_output=True)
        subprocess.run([spreadex(), "run", "-j", "4"], cwd=project, env=env, check=True, capture_output=True)
        return project
    project.mkdir()
    if kind == "own":
        (project / "validate.py").write_text(VALIDATOR)
    return project


def main() -> int:
    from playwright.sync_api import sync_playwright

    shots = json.loads((GUIDES / "screenshots.json").read_text())
    wanted = sys.argv[1:] or list(shots)
    with tempfile.TemporaryDirectory(prefix="guides-") as tmp:
        base = Path(tmp)
        env = {k: v for k, v in os.environ.items() if k not in ("SPREADEX_HOST_GENERATORS", "PYTHONPATH")}
        env["SPREADEX_HOME"] = str(base / "home")
        forbidden = [str(base), str(Path.home()), os.environ.get("USER", "") and f"/{os.environ['USER']}/"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for kind in ("fresh", "own", "rhino"):
                ids = [i for i in wanted if shots[i]["project"] == kind]
                if not ids:
                    continue
                print(f"{kind}:")
                project = prepare(kind, base, env)
                for shot_id in ids:
                    ui = Workbench(project, env)
                    page = browser.new_page(viewport={"width": WIDTH, "height": 900}, color_scheme="light")
                    page.goto(ui.url)
                    page.wait_for_function("() => typeof S !== 'undefined' && S.booted")
                    try:
                        capture(page, shot_id, shots[shot_id], forbidden)
                    finally:
                        page.close()
                        ui.stop()
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
