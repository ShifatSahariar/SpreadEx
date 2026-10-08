"""Clean-install acceptance: SpreadEx as an installed product, on this machine.

Two journeys, through the installed `spreadex` command only:

  A. the bundled demo   -- `spreadex generators install`, then `spreadex demo`;
                           its manifest is compared with demo_expected.json.
  B. a stranger's SUT   -- a small JSON validator: `spreadex init` -> `doctor` -> `run`,
                           then the suggested rejection rule is added to spreadex.yaml by
                           hand (the supported interface) and the campaign is run again.
  R. the Rhino example  -- `spreadex runtimes install rhino` (pinned, SHA-256 verified),
                           `spreadex example rhino` -> doctor -> run with Fandango and
                           Grammarinator generating and Fuzz4All replaying a recording; the
                           manifest and priority order are compared with rhino_expected.json,
                           and a finding is replayed.

Isolation: a fresh SPREADEX_HOME and SPREADEX_CACHE in a temporary folder, and host
generators disabled, so every generator is installed from its pinned recipe here.

Usage (with SpreadEx installed in the active environment):
    python scripts/acceptance/run_acceptance.py --out acceptance-out
Exit status 0 only if every check passed. A JSON report and the logs, manifests and doctor
output are written to --out for inspection (CI uploads that folder on failure).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

VALIDATOR = '''import json, sys
try:
    json.loads(open(sys.argv[1]).read())
except json.JSONDecodeError as e:
    print(f"invalid: {e}", file=sys.stderr)
    sys.exit(2)
print("ok")
'''

JSON_BNF = r'''<start> ::= <value>
<value> ::= <object> | <array> | <string> | <number> | "true" | "false" | "null"
<object> ::= "{}" | "{" <members> "}"
<members> ::= <pair> | <pair> "," <members>
<pair> ::= <string> ":" <value>
<array> ::= "[]" | "[" <elements> "]"
<elements> ::= <value> | <value> "," <elements>
<string> ::= "\"" <chars> "\""
<chars> ::= "" | <char> <chars>
<char> ::= "a" | "b" | "c" | "1" | " "
<number> ::= <digit> | <digit> <number>
<digit> ::= "0" | "1" | "2" | "9"
'''


class Report:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.checks: list[dict] = []
        self.timings: dict[str, float] = {}
        self.notes: dict[str, object] = {}

    def check(self, journey: str, name: str, ok: bool, detail: object = "") -> bool:
        self.checks.append({"journey": journey, "check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {journey}: {name}" + (f" -- {detail}" if detail and not ok else ""))
        return bool(ok)

    def ok(self, journey: str | None = None) -> bool:
        return all(c["ok"] for c in self.checks if journey is None or c["journey"] == journey)

    def write(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "report.json").write_text(json.dumps({
            "platform": platform.platform(), "python": sys.version.split()[0],
            "passed": self.ok(), "journeys": {j: self.ok(j) for j in ("demo", "stranger", "rhino")},
            "timings_s": self.timings, "notes": self.notes, "checks": self.checks}, indent=1))


def spreadex_exe() -> str:
    """The `spreadex` installed beside this interpreter, else the one on PATH."""
    bindir = Path(sys.executable).parent
    for name in ("spreadex", "spreadex.exe"):
        if (bindir / name).exists():
            return str(bindir / name)
    found = shutil.which("spreadex")
    if not found:
        sys.exit("spreadex is not installed in this environment (pip install . first)")
    return found


def run(cmd: list[str], cwd: Path, env: dict, log: Path, timeout: int = 1800) -> tuple[int, str, float]:
    start = time.time()
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    elapsed = time.time() - start
    output = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else "")
    log.write_text(f"$ {' '.join(cmd)}\n(cwd {cwd}, exit {proc.returncode}, {elapsed:.1f}s)\n\n{output}")
    return proc.returncode, output, elapsed


def latest_manifest(project: Path) -> dict | None:
    runs = sorted((project / ".spreadex" / "runs").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(runs[-1].read_text()) if runs else None


def first_finding(manifest: dict) -> int | None:
    return next((executed for executed, sigs in manifest["results"]["budget_curve"] if sigs > 0), None)


def keep_artifacts(project: Path, dest: Path) -> None:
    """Manifests and results only: never the blobs or the generator environments."""
    for f in (project / ".spreadex" / "runs").glob("*/*.json*"):
        target = dest / f.parent.name / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    if (project / "spreadex.yaml").exists():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / "spreadex.yaml", dest / "spreadex.yaml")


# ----------------------------------------------------------------------- journey A

def demo_journey(r: Report, exe: str, work: Path, env: dict, cache: Path) -> None:
    expected = json.loads((HERE / "demo_expected.json").read_text())
    logs = r.out / "demo"
    logs.mkdir(parents=True, exist_ok=True)
    print("\nA. bundled demo")

    # First-run installation of the pinned generators, timed one by one.
    for gid in expected["generators"]:
        code, out, t = run([exe, "generators", "install", gid], work, env, logs / f"install-{gid}.log")
        r.timings[f"install_{gid}"] = round(t, 1)
        r.check("demo", f"generator {gid} installs into the isolated cache", code == 0 and (cache / "generators" / gid).is_dir(),
                out[-400:])

    code, out, t = run([exe, "demo"], work, env, logs / "demo.log")
    r.timings["demo_run"] = round(t, 1)
    project = work / "spreadex-demo"
    keep_artifacts(project, logs)
    if not r.check("demo", "campaign completes", code == 0, out[-600:]):
        return
    m = latest_manifest(project)
    if not r.check("demo", "manifest written", m is not None):
        return
    corpus, results = m["corpus"], m["results"]
    counts = corpus.get("generator_counts", {})
    sel = corpus.get("selection") or {}
    scores = sel.get("scores", {})
    observed = {
        "generator_counts": counts, "selection": sel, "executed": results["executed"],
        "verdicts": results["verdicts"], "signatures": len(results["signatures"]),
        "first_finding_position": first_finding(m)}
    r.notes["demo_observed"] = observed

    r.check("demo", "three generators each produced their inputs",
            all(counts.get(g) == expected["inputs_per_generator"] for g in expected["generators"]), counts)
    r.check("demo", "CC selection occurred", bool(sel.get("selected")), sel)
    r.check("demo", "Fandango is selected", sel.get("selected") == expected["selected"], sel.get("selected"))
    r.check("demo", "FuzzingBook and Grammarinator are not selected",
            sorted(sel.get("dropped", [])) == sorted(expected["dropped"]), sel.get("dropped"))
    r.check("demo", "CC scores match the frozen evidence",
            all(abs(scores.get(g, -1) - v) < 1e-4 for g, v in expected["cc"].items()), scores)
    r.check("demo", f"{expected['executed']} inputs execute", results["executed"] == expected["executed"], results["executed"])
    r.check("demo", f"{expected['crash_inputs']} crashing inputs",
            results["verdicts"].get("crash", 0) == expected["crash_inputs"], results["verdicts"])
    r.check("demo", f"{expected['signatures']} signatures", len(results["signatures"]) == expected["signatures"],
            len(results["signatures"]))
    r.check("demo", f"first finding at position {expected['first_finding_position']}",
            first_finding(m) == expected["first_finding_position"], first_finding(m))
    r.check("demo", "no expected rejections",
            results["verdicts"].get("expected_rejection", 0) == expected["expected_rejections"], results["verdicts"])


# ----------------------------------------------------------------------- journey R

def rhino_journey(r: Report, exe: str, work: Path, env: dict, cache: Path) -> None:
    import hashlib
    import sqlite3

    expected = json.loads((HERE / "rhino_expected.json").read_text())
    logs = r.out / "rhino"
    logs.mkdir(parents=True, exist_ok=True)
    print("\nR. the Rhino example")

    code, out, t = run([exe, "runtimes", "install", "rhino"], work, env, logs / "runtime.log")
    r.timings["install_runtime_rhino"] = round(t, 1)
    jar = cache / "runtimes" / "rhino" / "1.9.1" / "rhino-all-1.9.1.jar"
    r.check("rhino", "the pinned Rhino downloads and verifies", code == 0 and jar.is_file() and "verified" in out,
            out[-400:])
    project = work / "spreadex-rhino"
    code, out, _ = run([exe, "example", "rhino", str(project)], work, env, logs / "example.log")
    if not r.check("rhino", "`spreadex example rhino` writes the project", code == 0 and (project / "spreadex.yaml").is_file(),
                   out[-400:]):
        return
    for gid in ("fandango", "grammarinator"):
        code, out, t = run([exe, "generators", "install", gid], project, env, logs / f"install-{gid}.log")
        r.timings[f"rhino_install_{gid}"] = round(t, 1)
        r.check("rhino", f"{gid} installs", code == 0, out[-400:])
    code, out, _ = run([exe, "doctor"], project, env, logs / "doctor.log")
    r.check("rhino", "doctor passes (Java, runtime, generators, recording)", code == 0, out[-800:])
    r.check("rhino", "doctor verifies the Fuzz4All recording", "replays a recording: 100 of 100 inputs" in out, out[-800:])

    code, out, t = run([exe, "run", "-j", "4"], project, env, logs / "run.log")
    r.timings["rhino_run"] = round(t, 1)
    keep_artifacts(project, logs)
    if not r.check("rhino", "campaign completes", code == 0, out[-600:]):
        return
    r.check("rhino", "the infinite loop is reported as a timeout, not as a confirmed defect",
            "timeout" in out and "Crashes ............... 0" in out
            and not any(w in out.lower() for w in ("defect", "bug found", "found a bug")), out[-1200:])
    r.check("rhino", "the report says Fuzz4All was replayed, not generated",
            "REPLAYED from a saved recording" in out and "not a controlled comparison" in out, out[-1200:])
    m = latest_manifest(project)
    corpus, results = m["corpus"], m["results"]
    sel = corpus.get("selection") or {}
    sources = {st["generator"]: st.get("source") for st in corpus.get("generation_stats") or []}
    db = sqlite3.connect(project / ".spreadex" / "corpus.db")
    order = [h for (h,) in db.execute("SELECT blob_hash FROM executions WHERE run_id=? ORDER BY rank", (m["run_id"],))]
    failing = [rk for (rk,) in db.execute(
        "SELECT rank FROM executions WHERE run_id=? AND verdict IN ('crash','timeout') ORDER BY rank", (m["run_id"],))]
    db.close()
    digest = hashlib.sha256(("\n".join(order) + "\n").encode()).hexdigest()
    runtime = (m["targets"][0].get("runtimes") or [{}])[0]
    r.notes["rhino_observed"] = {"generator_counts": corpus.get("generator_counts"), "sources": sources,
                                 "selection": sel, "verdicts": results["verdicts"],
                                 "signatures": len(results["signatures"]), "first_failing_rank": failing[:1],
                                 "priority_order_sha256": digest}
    r.check("rhino", "equal requested counts; actual counts as frozen",
            corpus.get("generator_counts") == {g: expected["inputs_per_generator"] for g in expected["generators"]},
            corpus.get("generator_counts"))
    r.check("rhino", "generation modes are labelled", sources == expected["sources"], sources)
    r.check("rhino", "the manifest names the pinned runtime",
            runtime.get("version") == "1.9.1" and runtime.get("verified") is True and runtime.get("sha256") ==
            "1cc2b468a51857747dcb29ae533e352a2abc04e81c5aa61e397dc774dd395329", runtime)
    r.check("rhino", "grammar checksums are recorded", set(corpus.get("grammars") or {}) == {"fandango", "grammarinator"},
            corpus.get("grammars"))
    r.check("rhino", "CC selection as frozen", sel.get("selected") == expected["selected"]
            and sorted(sel.get("dropped", [])) == sorted(expected["dropped"]), sel)
    r.check("rhino", "CC scores as frozen",
            all(abs((sel.get("scores") or {}).get(g, -1) - v) < 1e-4 for g, v in expected["cc"].items()), sel.get("scores"))
    r.check("rhino", "verdicts as frozen", results["verdicts"] == expected["verdicts"]
            and results["executed"] == expected["executed"], results["verdicts"])
    r.check("rhino", "signatures as frozen", len(results["signatures"]) == expected["signatures"], len(results["signatures"]))
    r.check("rhino", "first failing input at the frozen priority rank", failing[:1] == [expected["first_failing_rank"]], failing[:3])
    r.check("rhino", "the whole priority order is identical", digest == expected["priority_order_sha256"], digest)
    code, out, _ = run([exe, "replay", m["run_id"]], project, env, logs / "replay.log")
    r.check("rhino", "the campaign can be replayed", code == 0, out[-600:])


# ----------------------------------------------------------------------- journey B

def stranger_journey(r: Report, exe: str, work: Path, env: dict) -> None:
    logs = r.out / "stranger"
    logs.mkdir(parents=True, exist_ok=True)
    print("\nB. a stranger's SUT")
    project = work / "my-json-validator"          # does not exist yet: init creates it

    code, out, _ = run([exe, "init", str(project), "--command", "python", "validate.py", "{input}",
                        "--grammar", "json.bnf"], work, env, logs / "init.log")
    if not r.check("stranger", "init creates the new project directory",
                   code == 0 and (project / "spreadex.yaml").is_file(), out[-400:]):
        return
    (project / "validate.py").write_text(VALIDATOR)
    (project / "json.bnf").write_text(JSON_BNF)

    code, out, _ = run([exe, "generators", "install", "fuzzingbook"], project, env, logs / "install.log")
    code, out, _ = run([exe, "doctor"], project, env, logs / "doctor.log")
    runs_line = next((l for l in out.splitlines() if "target 'sut' runs" in l), "")
    r.check("stranger", "doctor says the target can actually start", code == 0 and "✓" in runs_line,
            runs_line or out[-600:])

    code, out, _ = run([exe, "run"], project, env, logs / "run-1.log")
    keep_artifacts(project, logs / "run-1")
    if not r.check("stranger", "campaign completes", code == 0, out[-600:]):
        return
    m = latest_manifest(project)
    v = m["results"]["verdicts"]
    r.notes["stranger_first_run"] = v
    r.check("stranger", "valid inputs pass (not misreported as setup failures)", v.get("ok", 0) > 0, v)
    r.check("stranger", "the two invalid observations are failures before configuration",
            v.get("crash", 0) == 2 and not v.get("expected_rejection"), v)
    r.check("stranger", "SpreadEx suggests the rejection pattern",
            "look like your system REJECTING input" in out and '"^invalid"' in out, out[-800:])
    import yaml
    oracle = (yaml.safe_load((project / "spreadex.yaml").read_text()) or {}).get("oracle") or {}
    r.check("stranger", "the suggestion is not applied automatically",
            not oracle.get("rejection_patterns"), oracle)

    # Phase 2: the user accepts the suggestion by editing spreadex.yaml, the supported interface.
    cfg = yaml.safe_load((project / "spreadex.yaml").read_text())
    cfg.setdefault("oracle", {})["rejection_patterns"] = ["^invalid"]
    (project / "spreadex.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    code, out, _ = run([exe, "run"], project, env, logs / "run-2.log")
    keep_artifacts(project, logs / "run-2")
    m2 = latest_manifest(project)
    v2 = m2["results"]["verdicts"] if m2 else {}
    r.notes["stranger_second_run"] = v2
    r.check("stranger", "with the rule configured, those inputs are expected rejections",
            code == 0 and v2.get("expected_rejection") == 2 and not v2.get("crash"), v2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="acceptance-out", help="where to write the report and logs")
    ap.add_argument("--only", choices=["demo", "stranger", "rhino"], help="run one journey")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    shutil.rmtree(out, ignore_errors=True)
    r = Report(out)
    exe = spreadex_exe()
    with tempfile.TemporaryDirectory(prefix="spreadex-acceptance-") as tmp:
        tmp = Path(tmp)
        home, cache, work = tmp / "home", tmp / "cache", tmp / "work"
        for d in (home, cache, work):
            d.mkdir()
        env = {k: v for k, v in os.environ.items()
               if k not in ("SPREADEX_HOST_GENERATORS", "PYTHONPATH")}
        env.update(SPREADEX_HOME=str(home), SPREADEX_CACHE=str(cache))
        print(f"spreadex: {exe}\nisolated home: {home}\nisolated generator cache: {cache}")
        if args.only in (None, "demo"):
            demo_journey(r, exe, work, env, cache)
        if args.only in (None, "stranger"):
            stranger_journey(r, exe, work, env)
        if args.only in (None, "rhino"):
            rhino_journey(r, exe, work, env, cache)
    r.write()
    print(f"\nreport: {out / 'report.json'}")
    print("ACCEPTANCE " + ("PASSED" if r.ok() else "FAILED"))
    return 0 if r.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
