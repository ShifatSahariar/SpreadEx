"""spreadex -- command line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .. import __version__
from ..core.campaign import Campaign
from ..core.config import ConfigError, find_config, load_config, render_template
from ..corpus import CorpusStore
from . import doctor as doctor_mod


def _die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _load(args) -> "object":
    try:
        return load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        _die(str(exc))


# --------------------------------------------------------------------- init

def cmd_init(args) -> int:
    root = Path(args.directory or ".").resolve()
    cfg_path = root / "spreadex.yaml"
    if cfg_path.exists() and not args.force:
        _die(f"{cfg_path} already exists (use --force to overwrite)")

    command = args.command or ["./your-parser", "{input}"]
    text = render_template(command, grammar=args.grammar, oracle="crash")
    cfg_path.write_text(text)

    state = root / ".spreadex"
    state.mkdir(exist_ok=True)
    gitignore = state / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# SpreadEx local state: corpora and runs stay out of git.\n*\n")

    print(f"Created {cfg_path}")
    print(f"Created {state}/ (git-ignored)")
    print("\nNext:")
    print("  1. edit spreadex.yaml -- set sut.command and an input source")
    print("  2. spreadex doctor")
    print("  3. spreadex run")
    return 0


# ------------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        # A missing file is something doctor reports as a check. A file that
        # exists but cannot be loaded is a different problem, and hiding its
        # message behind "not found" sends the user in the wrong direction.
        if find_config(Path(args.config) if args.config else None) is None and not args.config:
            config = None
        else:
            print("SpreadEx doctor\n")
            print(f"  \u2717 spreadex.yaml could not be loaded\n")
            for line in str(exc).splitlines():
                print(f"      {line}")
            return 1
    checks = doctor_mod.run_checks(config)
    print("SpreadEx doctor\n")
    for c in checks:
        print(c.render())
    ok, warn, fail = doctor_mod.summarize(checks)
    print(f"\n{ok} ok, {warn} warning(s), {fail} problem(s)")
    if fail:
        print("\nFix the problems above, then re-run `spreadex doctor`.")
        return 1
    print("Ready. Run `spreadex run`.")
    return 0


# ---------------------------------------------------------------------- run

def cmd_run(args) -> int:
    config = _load(args)
    if args.budget:
        from ..exec.runner import _parse_duration
        config.budget.execution_s = _parse_duration(args.budget)
    if args.max_inputs:
        config.budget.max_inputs = args.max_inputs

    campaign = Campaign(config)
    try:
        result = campaign.run(signal_override=args.signal, jobs=args.jobs)
    except RuntimeError as exc:
        _die(str(exc), code=1)

    _print_result(result, config)
    if args.fail_on == "new-failure" and result.new_signatures:
        print(f"\nFAIL: {len(result.new_signatures)} new failure signature(s).")
        return 1
    if args.fail_on == "any-failure" and result.failures:
        print(f"\nFAIL: {result.failures} failing input(s).")
        return 1
    return 0


def _print_result(r, config) -> None:
    v = r.verdicts
    print("\nSpreadEx Campaign\n")
    print("  Corpus")
    print(f"    Generated ............. {r.generated}")
    print(f"    Valid ................. {r.valid}")
    print(f"    Prioritized ........... {r.prioritized}")
    if r.generator_scores and len(r.generator_scores) > 1:
        print("\n  Generator comparison" + (f"  (k_eff={r.k_eff})" if r.k_eff else ""))
        print(f"    {'generator':<16} {'CC':>5} {'inputs':>7} {'gen cost':>10}")
        for g, s in sorted(r.generator_scores.items(), key=lambda kv: -kv[1]):
            n = r.generator_counts.get(g, 0)
            cost_s = r.generator_cost_ms.get(g, 0.0) / 1000
            bar = "#" * int(round(s * 20))
            print(f"    {g:<16} {s:>5.2f} {n:>7} {cost_s:>9.1f}s  {bar}")
        # Cluster coverage is comparable only when the generators were given a
        # comparable chance. Wildly different costs mean the comparison is
        # equal-count, not equal-budget -- say so rather than let it mislead.
        costs = [c for c in r.generator_cost_ms.values() if c > 0]
        if len(costs) > 1 and max(costs) > 5 * min(costs):
            print("    note: generation costs differ by more than 5x, so these "
                  "CC values compare\n          equal INPUT COUNTS, not equal budgets.")
    print("\n  Execution")
    print(f"    Executed .............. {r.executed}")
    print(f"    Budget ................ {r.exec_budget_s:.1f} s "
          f"(used {r.exec_elapsed_s:.1f} s)")
    print(f"    Passed ................ {v.get('ok', 0)}")
    print(f"    Rejected (expected) ... {v.get('expected_rejection', 0)}")
    print(f"    Crashes ............... {v.get('crash', 0)}")
    print(f"    Timeouts .............. {v.get('timeout', 0)}")
    if config.is_differential:
        print(f"    Divergences ........... {v.get('divergence', 0)}")
    print(f"\n  Failure signatures ...... {len(r.signatures)}"
          f"   ({len(r.new_signatures)} new)")
    if r.signatures:
        print("    (a signature is not a bug -- distinct bugs can share one, "
              "and one bug can span several)")
        for sig, verdict, n in r.signatures[:10]:
            print(f"      {sig}  {verdict:<11} x{n}")
    if r.budget_curve and r.signatures:
        print("\n  Budget curve (distinct signatures vs inputs executed)")
        total = r.budget_curve[-1][1] or 1
        marks = []
        n = len(r.budget_curve)
        for frac in (0.1, 0.25, 0.5, 1.0):
            i = max(0, min(n - 1, int(n * frac) - 1))
            executed, sigs = r.budget_curve[i]
            marks.append((executed, sigs))
        for executed, sigs in marks:
            bar = "#" * int(round(30 * sigs / total))
            print(f"    after {executed:>5} inputs: {sigs:>3} signature(s)  {bar}")
        first = next((e for e, s in r.budget_curve if s > 0), None)
        if first:
            print(f"    first failure at input {first} of {r.executed}")

    print(f"\n  Results: {r.run_dir}")
    print(f"  Replay:  spreadex replay {r.run_id}")


# --------------------------------------------------------------- generators

def cmd_generators(args) -> int:
    from ..generators import GeneratorError, GeneratorManager

    mgr = GeneratorManager()
    if args.generators_action == "list":
        print("Generators\n")
        for st in mgr.status_all():
            g = st.generator
            if st.installed:
                mark, note = "\u2713", f"installed ({st.version or 'version unknown'}, {st.where})"
            else:
                mark, note = "\u2717", "not installed"
            print(f"  {mark} {g.name:<16} {note}")
            print(f"      grammar: {g.grammar_dialect}"
                  f"{'  constraints: yes' if g.supports_constraints else ''}")
            if g.notes:
                print(f"      note: {g.notes}")
        print("\nInstall with: spreadex generators install <id>")
        return 0

    try:
        for gid in args.ids:
            print(f"{mgr.get(gid).name}")
            mgr.install(gid, upgrade=args.upgrade)
    except GeneratorError as exc:
        _die(str(exc), code=1)
    return 0


# ------------------------------------------------------------------- report

def cmd_report(args) -> int:
    config = _load(args)
    with CorpusStore(config.state_dir) as store:
        runs = store.list_runs(limit=args.limit)
        if not runs:
            print("No runs yet. Run `spreadex run`.")
            return 0
        print(f"{'RUN':<22} {'SIGNAL':<8} {'EXECUTED':>9} {'FAILURES':>9}  FINISHED")
        for r in runs:
            summ = store.run_summary(r["run_id"])
            executed = sum(summ.values())
            failures = sum(summ.get(k, 0) for k in ("crash", "timeout", "divergence"))
            print(f"{r['run_id']:<22} {(r['signal_name'] or '-'):<8} "
                  f"{executed:>9} {failures:>9}  {r['finished_at'] or 'incomplete'}")
    return 0


# ------------------------------------------------------------------- replay

def cmd_replay(args) -> int:
    config = _load(args)
    with CorpusStore(config.state_dir) as store:
        run_id = args.run_id or store.latest_run_id()
        if not run_id:
            _die("no runs found")
        mpath = store.run_dir(run_id) / "manifest.json"
        if not mpath.exists():
            _die(f"no manifest for run {run_id}")
        manifest = json.loads(mpath.read_text())

    print(f"Run {run_id}")
    print(f"  spreadex     {manifest.get('spreadex_version')}")
    print(f"  config hash  {manifest.get('config_hash')}")
    print(f"  seed         {manifest.get('seed')}   signal: {manifest.get('signal')}")
    for t in manifest.get("targets", []):
        print(f"  target       {t['name']}: {' '.join(t['command'])}  [{t.get('version') or 'unknown version'}]")
    env = manifest.get("environment", {})
    print(f"  environment  python {env.get('python')} on {env.get('platform')}")

    # A run may have been launched with CLI overrides (--budget, --signal).
    # Re-apply them before comparing, otherwise every overridden run looks like
    # configuration drift.
    eff = manifest.get("effective") or {}
    if eff:
        config.budget.generation_s = eff.get("generation_s", config.budget.generation_s)
        config.budget.execution_s = eff.get("execution_s", config.budget.execution_s)
        config.budget.max_inputs = eff.get("max_inputs", config.budget.max_inputs)

    current = config.hash()
    if current != manifest.get("config_hash"):
        print(f"\n  ! spreadex.yaml has changed since this run "
              f"(now {current}, then {manifest.get('config_hash')}).")
        print("    A replay will NOT reproduce it. Check out the matching config first.")
        if not args.force:
            return 1
    if not args.execute:
        print("\nConfiguration matches. Re-run it with:")
        print(f"  spreadex replay {run_id} --execute")
        return 0

    print("\nReplaying...")
    result = Campaign(config).run(signal_override=manifest.get("signal"))
    _print_result(result, config)
    return 0


# ------------------------------------------------------------------- export

def cmd_export(args) -> int:
    config = _load(args)
    out = Path(args.output or "campaign.zip").resolve()
    with CorpusStore(config.state_dir) as store:
        run_id = args.run_id or store.latest_run_id()
        if not run_id:
            _die("no runs to export")
        run_dir = store.run_dir(run_id)

    import tempfile, zipfile
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "campaign"
        stage.mkdir()
        shutil.copytree(run_dir, stage / "run", dirs_exist_ok=True)
        shutil.copy2(config.project_root / "spreadex.yaml", stage / "spreadex.yaml")

        # Ship the actual inputs behind each failure: a manifest that names a
        # hash nobody else can resolve is not a reproduction.
        with CorpusStore(config.state_dir) as store:
            rows = store.conn.execute(
                """SELECT DISTINCT blob_hash, signature, verdict FROM executions
                   WHERE run_id=? AND verdict IN ('crash','timeout','divergence')""",
                (run_id,),
            ).fetchall()
            if rows:
                fdir = stage / "failing_inputs"
                fdir.mkdir()
                index = []
                for r in rows:
                    data = store.get_blob(r["blob_hash"])
                    fname = f"{r['verdict']}-{(r['signature'] or 'none')[:12]}-{r['blob_hash'][:8]}"
                    (fdir / fname).write_bytes(data)
                    index.append({"file": fname, **dict(r)})
                (stage / "failing_inputs" / "index.json").write_text(
                    json.dumps(index, indent=2)
                )
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in stage.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(stage))
    print(f"Exported {run_id} -> {out}")
    print("  contains: manifest.json, results.jsonl, spreadex.yaml, failing inputs")
    return 0


# --------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spreadex",
        description="Run several grammar-based generators against a system under test "
                    "and spend a finite budget on the inputs most worth executing. "
                    "Everything runs locally.",
    )
    p.add_argument("--version", action="version", version=f"spreadex {__version__}")
    p.add_argument("-c", "--config", help="path to spreadex.yaml")
    sub = p.add_subparsers(dest="command_name", required=True)

    s = sub.add_parser("init", help="create spreadex.yaml in this project")
    s.add_argument("directory", nargs="?", help="project root (default: .)")
    s.add_argument("--command", nargs="+", help="SUT command, e.g. --command java -jar sut.jar '{input}'")
    s.add_argument("--grammar", default="grammar.g4")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="check the setup and print fixes")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("run", help="run a campaign")
    s.add_argument("--budget", help="execution budget, e.g. 60s, 10m")
    s.add_argument("--selection-signal", dest="signal", metavar="NAME",
                   help="cc (default) | random. Ordinary use needs no choice; "
                        "this exists for experiments.")
    s.add_argument("--max-inputs", type=int)
    s.add_argument("-j", "--jobs", type=int, default=1,
                   help="parallel executions (default 1; >1 is faster but makes "
                        "durations noisier and can cause borderline timeouts)")
    s.add_argument("--fail-on", choices=["never", "new-failure", "any-failure"], default="never",
                   help="exit non-zero on failures (for CI)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("generators", help="list or install input generators")
    gsub = s.add_subparsers(dest="generators_action", required=True)
    gl = gsub.add_parser("list", help="show which generators are available")
    gl.set_defaults(func=cmd_generators)
    gi = gsub.add_parser("install", help="install generators into isolated environments")
    gi.add_argument("ids", nargs="+")
    gi.add_argument("--upgrade", action="store_true")
    gi.set_defaults(func=cmd_generators)
    s.set_defaults(func=cmd_generators)

    s = sub.add_parser("report", help="list past runs")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("replay", help="inspect or re-run a past campaign")
    s.add_argument("run_id", nargs="?")
    s.add_argument("--execute", action="store_true", help="actually re-run it")
    s.add_argument("--force", action="store_true", help="replay even if the config changed")
    s.set_defaults(func=cmd_replay)

    s = sub.add_parser("export", help="export a campaign as a zip")
    s.add_argument("run_id", nargs="?")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
