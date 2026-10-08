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
    root.mkdir(parents=True, exist_ok=True)     # `spreadex init new-project` creates it
    cfg_path = root / "spreadex.yaml"
    if cfg_path.exists() and not args.force:
        _die(f"{cfg_path} already exists (use --force to overwrite)")

    command = args.command or ["./your-parser", "{input}"]
    text = render_template(command, grammar=args.grammar or "grammar.g4", oracle="crash")
    cfg_path.write_text(text)

    # The corpus store writes the directory and its .gitignore, so a project
    # that never ran `init` is protected too.
    from ..corpus import CorpusStore

    state = root / ".spreadex"
    with CorpusStore(state):
        pass

    print(f"Created {cfg_path}")
    print(f"Created {state}/ (git-ignored)")
    # Ask only for what was not given on the command line.
    todo = []
    if not args.command:
        todo.append("set sut.command")
    if not args.grammar:
        todo.append("set an input source (grammar.source or corpus.path)")
    steps = ([f"edit spreadex.yaml -- {' and '.join(todo)}"] if todo else []) + [
        "spreadex doctor   (runs your system once to check the setup)", "spreadex run"]
    print("\nNext:")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    return 0


# ------------------------------------------------------------------- doctor

def _print_checks(heading: str, checks) -> None:
    print(f"{heading}")
    for c in checks:
        print(c.render())
    print()


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
            _print_checks("Installation", doctor_mod.installation_checks())
            print(f"  \u2717 spreadex.yaml could not be loaded\n")
            for line in str(exc).splitlines():
                print(f"      {line}")
            return 1
    checks = doctor_mod.run_checks(config)
    print("SpreadEx doctor\n")
    _print_checks("Installation", doctor_mod.installation_checks())
    _print_checks("This project", checks)
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


def _warn_if_cc_is_really_volume(r, pool: int) -> None:
    """CC is pool-relative, so an unequal pool makes it partly a volume count.

    CC(g) is the share of clusters g touches. A generator contributing most of
    the inputs touches most of the clusters almost by construction, so when the
    shares are lopsided a high CC is not evidence of better coverage -- it is
    partly evidence of having been faster. Equal-time budgeting makes this MORE
    likely, not less, which is the honest trade it carries.
    """
    shares = {g: n / pool for g, n in r.generator_counts.items() if pool}
    if len(shares) < 2:
        return
    top, top_share = max(shares.items(), key=lambda kv: kv[1])
    if top_share < 0.5:
        return
    print(f"    ! {top} supplied {100 * top_share:.0f}% of the pool. CC is measured "
          f"over that pool,\n      so a generator contributing most of it touches most "
          f"clusters almost by\n      construction -- read this ranking as partly a "
          f"throughput ranking.")


def _print_result(r, config) -> None:
    v = r.verdicts
    print("\nSpreadEx Campaign\n")
    print("  Corpus")
    print(f"    Generated ............. {r.generated}")
    print(f"    Valid ................. {r.valid}")
    print(f"    Prioritized ........... {r.prioritized}")
    if r.generator_scores and len(r.generator_scores) > 1:
        print("\n  Generator comparison" + (f"  (k_eff={r.k_eff})" if r.k_eff else ""))
        by_gen = {st["generator"]: st for st in (r.generation_stats or [])}
        mode = next(iter(by_gen.values()), {}).get("mode", "count")
        pool = sum(r.generator_counts.values()) or 1
        print(f"    {'generator':<16} {'CC':>5} {'inputs':>7} {'% pool':>7} "
              f"{'gen cost':>10} {'rate/s':>8}")
        for g, s in sorted(r.generator_scores.items(), key=lambda kv: -kv[1]):
            n = r.generator_counts.get(g, 0)
            cost_s = r.generator_cost_ms.get(g, 0.0) / 1000
            rate = by_gen.get(g, {}).get("throughput_per_s", 0.0)
            bar = "#" * int(round(s * 20))
            if by_gen.get(g, {}).get("source") == "recorded":
                # Replayed, so this run spent nothing generating them: no cost or rate to show.
                print(f"    {g:<16} {s:>5.2f} {n:>7} {100 * n / pool:>6.1f}% "
                      f"{'recorded':>10} {'-':>8}  {bar}")
                continue
            print(f"    {g:<16} {s:>5.2f} {n:>7} {100 * n / pool:>6.1f}% "
                  f"{cost_s:>9.1f}s {rate:>8.1f}  {bar}")
        replayed = sorted(g for g, st in by_gen.items() if st.get("source") == "recorded")
        if replayed:
            print(f"    ! {', '.join(replayed)}: inputs REPLAYED from a saved recording, not generated in "
                  f"this run,\n      so this is not a controlled comparison of the generators.")

        # Cluster coverage is comparable only when the generators were given a
        # comparable chance, so the basis of the comparison is stated every
        # time rather than left for the reader to infer from the cost column.
        if mode == "time":
            secs = next((st.get("requested_seconds") for st in by_gen.values()
                         if st.get("requested_seconds")), None)
            budget = f"{secs:.0f}s each" if secs else "an equal share of time"
            print(f"    basis: EQUAL TIME ({budget}). Inputs differ because the "
                  f"generators differ,\n           which is the comparison you want "
                  f"when deciding where budget goes.")
            # Hitting the ceiling is not the same as finishing early, and a
            # generator that produced nothing did neither.
            capped = sorted(g for g, st in by_gen.items() if st.get("hit_cap"))
            if capped:
                print(f"    ! {', '.join(capped)} stopped before using the full share, "
                      f"having hit\n      `generation.cap`. Raise the cap or these are "
                      f"not really equal-time.")
            silent = sorted(g for g in r.generator_scores
                            if by_gen.get(g, {}).get("produced", 0) == 0)
            if silent:
                print(f"    ! {', '.join(silent)} produced nothing in the time given, "
                      f"which is a result:\n      on this grammar it cannot deliver at "
                      f"this budget.")
            _warn_if_cc_is_really_volume(r, pool)
        else:
            _warn_if_cc_is_really_volume(r, pool)
            counts = set(r.generator_counts.values())
            costs = [c for c in r.generator_cost_ms.values() if c > 0]
            same = f"{next(iter(counts))} each" if len(counts) == 1 else "a fixed count each"
            print(f"    basis: EQUAL INPUT COUNT ({same}), which is reproducible but "
                  f"not resource-fair.")
            if len(costs) > 1 and max(costs) > 5 * min(costs):
                print(f"    ! those counts cost between {min(costs)/1000:.1f}s and "
                      f"{max(costs)/1000:.1f}s to produce\n"
                      f"      ({max(costs)/min(costs):.0f}x), so CC here does NOT compare "
                      f"equal budgets.\n"
                      f"      Fix: `generation: {{mode: time}}` to give each generator "
                      f"the same seconds.")
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

    _print_rejection_hints(r, config)
    print(f"\n  Results: {r.run_dir}")
    print(f"  Replay:  spreadex replay {r.run_id}")


def _print_rejection_hints(r, config) -> None:
    """Crashes that read like the system rejecting input: say so, and how to tell SpreadEx."""
    from ..core.firstrun import rejection_hints

    if not r.failures:
        return
    with CorpusStore(config.state_dir) as store:
        hints = rejection_hints(store, r.run_id)
    if not hints:
        return
    print("\n  ! Some of these crashes look like your system REJECTING input, not crashing:")
    for h in hints:
        print(f"      {h['inputs']} input(s), exit {h['exit_code']}: {h['line'][:90]}")
    print("    If that is your system's normal way to refuse invalid input, add to spreadex.yaml:")
    print("      oracle:")
    print("        rejection_patterns:")
    for h in hints:
        print(f"          - {json.dumps(h['pattern'])}")
    print("    and those inputs will count as expected rejections instead of findings.")

# ----------------------------------------------------------------------- ui

def cmd_ui(args) -> int:
    import webbrowser

    from ..api import registry, serve
    from ..core.config import Config

    if args.list:
        return _list_servers(registry)

    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        if args.config:
            # An explicit -c pointing at something broken is still fatal: the
            # user named a file, so silently ignoring it would be worse.
            _die(str(exc))
        config = Config.unconfigured(Path.cwd())

    if args.stop:
        try:
            stopped = registry.stop(config.project_root)
        except registry.Embedded as exc:
            print(f"This Workbench runs inside the one for {exc}; stop that one to stop both.")
            return 1
        if stopped:
            print(f"Stopped the Workbench for {config.project_root}")
            return 0
        print(f"No Workbench is running for {config.project_root}")
        return 0

    # Running it twice must not start a second server for the same project: reopen the first.
    if not args.port and not args.new_token:
        live = registry.find_live(config.project_root)
        if live:
            from ..api.server import project_token
            url = f"http://{live['host']}:{live['port']}/?token={project_token(config)}"
            print(f"\nThe Workbench for {config.project_root} is already running:\n\n  {url}\n")
            if not args.no_open:
                webbrowser.open(url)
            return 0

    try:
        serve(config, host=args.host, port=args.port,
              open_browser=not args.no_open, verbose=args.verbose,
              read_only=args.read_only, new_token=args.new_token,
              experimental=args.experimental)
    except OSError as exc:
        _die(f"could not start the UI on {args.host}:{args.port}: {exc}\n"
             f"  Fix: leave --port out and SpreadEx will pick a free one.", code=1)
    return 0


def _list_servers(registry) -> int:
    servers = registry.live_servers()
    if not servers:
        print("No Workbench is running.")
        return 0
    width = max(len(s["root"]) for s in servers)
    for s in servers:
        inside = f", inside {s['embedded_in']}" if s.get("embedded_in") else ""
        print(f"  {s['root']:<{width}}  http://{s['host']}:{s['port']}  (pid {s['pid']}{inside})")
    print("\nOpen one with `spreadex ui` from its folder; stop it with `spreadex ui --stop`.")
    return 0



# --------------------------------------------------------------------- demo

def _open_demo_ui(project: Path, args) -> int:
    """Open the Workbench on the demo project, so its results are one step away."""
    from ..api import serve

    config = load_config(project / "spreadex.yaml")
    print(f"\n  Opening the Workbench on {project} (Ctrl-C to stop)\n")
    try:
        serve(config, host="127.0.0.1", port=args.port, open_browser=True)
    except OSError as exc:
        _die(f"could not start the UI on 127.0.0.1:{args.port}: {exc}\n"
             f"  Fix: pass --port to pick another, or stop whatever is using it.", code=1)
    return 0


def cmd_example(args) -> int:
    """Write a bundled example project into a folder of its own, with its pinned runtime."""
    from .. import examples, runtimes

    try:
        ex = examples.get(args.name)
    except ValueError as exc:
        _die(str(exc))
    if ex.name == "minicalc":
        _die("MiniCalc is the demo: use `spreadex demo`")
    target = Path(args.directory or f"spreadex-{ex.name}").resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        _die(f"{target} already exists and is not empty.\n  Fix: choose another folder, or --force to "
             f"restore the example's missing files there (your edits and campaigns are kept).")
    try:
        for rt in ex.runtimes:
            runtimes.ensure(rt)
    except runtimes.RuntimeUnavailable as exc:
        _die(str(exc))
    examples.ensure(ex.name, target)
    print(f"{ex.title} example written to {target}")
    print(f"  {ex.summary}")
    print("\nNext:")
    print(f"  cd {target}")
    if ex.generators:
        print(f"  spreadex generators install {' '.join(ex.generators)}")
    print("  spreadex doctor\n  spreadex run")
    return 0


def cmd_demo(args) -> int:
    """Materialise the bundled demo project and run a real campaign in it.

    Everything here is genuine: the generators run, the inputs are clustered
    and prioritized, calc.py is executed, the oracle judges the results. The
    only thing we supply is the system under test, so that someone can see the
    pipeline work before they have configured anything of their own.
    """
    from ..demo import materialize

    target = Path(args.directory).resolve()
    try:
        project = materialize(target, force=args.force)
    except FileExistsError as exc:
        _die(str(exc), code=1)
    except OSError as exc:
        _die(f"could not write the demo to {target}: {exc}", code=1)

    print(f"Demo project written to {project}")
    print("  calc.py       the system under test -- about a hundred lines, worth reading")
    print("  calc.bnf      one grammar; SpreadEx derives each generator's dialect from it")
    print("  spreadex.yaml the campaign, exactly as it will run")
    if args.no_run:
        if args.ui:
            return _open_demo_ui(project, args)
        print(f"\nNext: cd {project} && spreadex run")
        return 0

    try:
        config = load_config(project / "spreadex.yaml")
    except ConfigError as exc:
        _die(str(exc), code=1)

    from ..demo import prepare_generators

    prepare_generators(config)

    print("\nRunning a real campaign. Nothing about this is canned.\n")
    campaign = Campaign(config)
    try:
        result = campaign.run(jobs=args.jobs)
    except RuntimeError as exc:
        _die(str(exc), code=1)
    _print_result(result, config)

    print("\nWhat to make of that:")
    rejected = result.verdicts.get("expected_rejection", 0)
    if rejected:
        print(f"  {rejected} input(s) were refused by calc.py and counted as expected")
        print("  rejections, not failures. That distinction is configured in spreadex.yaml")
        print("  and it is the difference between a usable tool and a noise generator.")
    if result.failures:
        print(f"  {result.failures} input(s) failed, across "
              f"{len(result.signatures)} signature(s). That is a real, documented defect:")
        print("  calc.py guards division by zero and never extended the guard to the")
        print("  remainder operator beside it. See its README.")
    else:
        print("  Nothing failed this time. calc.py does have a real defect -- an incomplete")
        print("  zero guard -- but whether a campaign reaches it depends on what the")
        print("  generators produced under this budget. A longer budget makes it likelier.")
    if args.ui:
        return _open_demo_ui(project, args)
    print(f"\n  Look closer:  cd {project} && spreadex ui")
    return 0


# ------------------------------------------------------------------ grammar

def cmd_grammar(args) -> int:
    from ..grammar import (
        RENDERERS, GrammarError, Severity, adapt, diagnose, expressibility, load,
    )

    source = Path(args.source)
    try:
        grammar = load(source, start=args.start)
    except (GrammarError, OSError) as exc:
        _die(str(exc), code=1)

    if args.grammar_action == "check":
        report = diagnose(grammar)
        feats = sorted(f.value for f in grammar.features())
        print(f"{source}\n")
        print(f"  {len(grammar.rules)} rules, start <{grammar.start}>")
        print(f"  uses: {', '.join(feats) if feats else 'plain BNF'}\n")
        seen_fix: set[str] = set()
        for finding in report.findings:
            text = finding.render()
            if finding.code in seen_fix and finding.fix:
                text = text.split("\n      fix:")[0]
            seen_fix.add(finding.code)
            print(text)
        if not report.findings:
            print("  no problems found")
        print("\n  Generator support")
        for gen in sorted(args.generators or RENDERERS):
            if gen not in RENDERERS:
                print(f"    - {gen:<14} SpreadEx cannot emit this dialect yet")
                continue
            exp = expressibility(grammar, gen)
            if not exp.usable:
                print(f"    \u2717 {gen:<14} {'; '.join(exp.blockers)[:90]}")
            elif exp.directly:
                print(f"    \u2713 {gen:<14} directly")
            else:
                need = ", ".join(sorted(f.value for f in exp.missing))
                print(f"    \u2713 {gen:<14} after rewriting ({need})")
            for risk in exp.risks:
                print(f"      ! {risk}")
        return 1 if report.errors else 0

    # adapt
    generators = args.generators or sorted(RENDERERS)
    result = adapt(source, generators, args.out or ".", start=args.start)
    if not result.ok and result.report.errors:
        print(f"{source} has errors; nothing was written.\n")
        for finding in result.report.errors:
            print(finding.render())
        return 1
    for gen, path in result.written.items():
        print(f"  wrote {path}  ({gen})")
    for gen, risks in result.risks.items():
        for risk in risks:
            print(f"  ! {gen}: {risk}")
    for gen, why in result.skipped.items():
        print(f"  skipped {gen}: {why}")
    return 0


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


def cmd_runtimes(args) -> int:
    from .. import runtimes

    if getattr(args, "action", None) != "install":
        for rt in runtimes.CATALOG.values():
            cached = runtimes.verified(rt.name)
            mark = "\u2713" if cached else "\u2717"
            print(f"  {mark} {rt.name:<8} {rt.title} {rt.version} ({rt.licence}, Java {rt.java_min}+)"
                  f"  {'installed' if cached else 'not installed'}")
            if rt.note:
                print(f"      {rt.note}")
        print("\nInstall with: spreadex runtimes install <name>")
        return 0
    try:
        for name in args.names:
            runtimes.ensure(name)
    except runtimes.RuntimeUnavailable as exc:
        _die(str(exc), code=1)
    return 0


# ------------------------------------------------------------------- report

def cmd_runs(args) -> int:
    """The same history the Workbench shows: list, cancel, or delete campaigns."""
    from ..api import data
    from ..core.lock import active_run, cancel_file

    config = _load(args)
    state = config.state_dir
    action = getattr(args, "runs_action", None) or "list"
    if not state.is_dir():
        print("No campaigns yet. Run one with `spreadex run`.")
        return 0
    if action == "list":
        runs = data.list_runs(state)
        if not runs:
            print("No campaigns yet. Run one with `spreadex run`.")
        for r in runs:
            size = r["size_bytes"] / 1024
            print(f"{r['run_id']:<24} {r['status']:<9} "
                  f"{(r['origin'] or '-'):<3} {r['executed']:>6} executed "
                  f"{r['findings']:>3} findings {size:8.1f} KiB")
        return 0
    info = active_run(state)
    if action == "cancel":
        if not info or info.get("run_id") != args.run_id:
            _die(f"{args.run_id} is not running.", code=1)
        cancel_file(state, args.run_id).write_text("")
        print(f"Asked {args.run_id} to stop after its current input.")
        return 0
    if action == "delete":
        if info is not None and info.get("run_id") in (args.run_id, None):
            _die(f"{args.run_id} is running; cancel it first with "
                 f"`spreadex runs cancel {args.run_id}`.", code=1)
        if not args.yes:
            answer = input(f"Permanently delete {args.run_id} and its results? [y/N] ")
            if answer.strip().lower() not in ("y", "yes"):
                print("Kept.")
                return 0
        with CorpusStore(state) as store:
            try:
                out = store.delete_run(args.run_id)
            except KeyError:
                _die(f"No run {args.run_id!r}.", code=1)
        print(f"Deleted {args.run_id}: {out['inputs_removed']} input(s) only it used, "
              f"{out['bytes_freed'] / 1024:.1f} KiB freed.")
        return 0
    return 2


def cmd_results(args) -> int:
    """The latest campaign by default; the history on request.

    Someone who just ran a campaign wants to know how it went, not to be
    handed a table of every run they have ever done.
    """
    config = _load(args)
    if not getattr(args, "all", False):
        return _show_one_run(config, getattr(args, "run_id", None))
    with CorpusStore(config.state_dir) as store:
        runs = store.list_runs(limit=args.limit)
        if not runs:
            print("No runs yet. Run `spreadex run`, or `spreadex demo` to see one.")
            return 0
        print(f"{'RUN':<22} {'SIGNAL':<8} {'EXECUTED':>9} {'FAILURES':>9}  FINISHED")
        for r in runs:
            summ = store.run_summary(r["run_id"])
            executed = sum(summ.values())
            failures = sum(summ.get(k, 0) for k in ("crash", "timeout", "divergence"))
            print(f"{r['run_id']:<22} {(r['signal_name'] or '-'):<8} "
                  f"{executed:>9} {failures:>9}  {r['finished_at'] or 'incomplete'}")
    return 0


def _show_one_run(config, run_id: str | None) -> int:
    with CorpusStore(config.state_dir) as store:
        run_id = run_id or store.latest_run_id()
        if not run_id:
            print("No campaigns yet.")
            print("  Try one:  spreadex demo")
            print("  Or yours: spreadex run")
            return 0
        summ = store.run_summary(run_id)
        if not summ:
            _die(f"no run {run_id!r}. `spreadex results --all` lists them.", code=1)
        executed = sum(summ.values())
        failures = sum(summ.get(k, 0) for k in ("crash", "timeout", "divergence"))
        sigs = store.signatures_in_run(run_id)

    print(f"Campaign {run_id}\n")
    print(f"  Executed .............. {executed}")
    print(f"  Passed ................ {summ.get('ok', 0)}")
    print(f"  Rejected (expected) ... {summ.get('expected_rejection', 0)}")
    print(f"  Failing ............... {failures}")
    if sigs:
        print(f"  Signatures ............ {len(sigs)}")
        print("    (a signature is not a bug -- distinct bugs can share one,")
        print("     and one bug can span several)")
        for row in sigs[:10]:
            print(f"      {row['signature']}  {row['verdict']:<11} x{row['n']}")
    print(f"\n  Everything else:  spreadex ui")
    print(f"  Reproduce:        spreadex replay {run_id}")
    print(f"  Every campaign:   spreadex results --all")
    return 0


# ------------------------------------------------------------------- replay

def cmd_record(args) -> int:
    """Save one generator's inputs from a past run as a recording, replayable without regenerating."""
    from ..generators.recorded import write
    from ..generators import GeneratorError

    config = _load(args)
    with CorpusStore(config.state_dir) as store:
        run_id = args.run_id
        listing = store.run_dir(run_id) / "inputs.jsonl"
        mpath = store.run_dir(run_id) / "manifest.json"
        if not listing.is_file():
            _die(f"run {run_id} has no list of its inputs (runs made before SpreadEx recorded one "
                 f"cannot be exported)")
        manifest = json.loads(mpath.read_text()) if mpath.is_file() else {}
        seen, inputs = set(), []
        for line in listing.read_text().splitlines():
            row = json.loads(line)
            if row["generator"] == args.generator and row["blob"] not in seen:
                seen.add(row["blob"])
                inputs.append(store.get_blob(row["blob"]))
    if not inputs:
        _die(f"{args.generator} produced no inputs in run {run_id}")
    stats = next((st for st in (manifest.get("corpus") or {}).get("generation_stats") or []
                  if st.get("generator") == args.generator), {})
    provenance = {
        "source": f"SpreadEx run {run_id}",
        "spreadex_version": manifest.get("spreadex_version"),
        "config_hash": manifest.get("config_hash"),
        "seed": manifest.get("seed"),
        "generation": stats,
        "note": "Saved from a past run: replaying reproduces these inputs exactly without regenerating them.",
    }
    try:
        write(Path(args.output), args.generator, inputs, provenance, suffix=args.suffix)
    except GeneratorError as exc:
        _die(str(exc))
    print(f"Recorded {len(inputs)} {args.generator} inputs from run {run_id} to {args.output}")
    print(f"Replay with:\n  generation:\n    {args.generator}: {{mode: recorded, corpus: {args.output}}}")
    return 0


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
    run_id, output = args.run_id, args.output
    # `spreadex export out.zip` is what people type. Reading that as a run id
    # and then failing on a missing run directory would be a riddle, so a
    # positional that is plainly a filename is taken as the destination.
    if run_id and output is None and run_id.endswith(".zip"):
        run_id, output = None, run_id
    from ..core.export import ExportError, build_export
    try:
        run_id, out = build_export(config, run_id, Path(output or "campaign.zip"))
    except ExportError as exc:
        _die(str(exc), code=1)
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
    # The metavar is set explicitly so hidden aliases stay out of the choices
    # line: argparse lists every registered name there, help text or not.
    sub = p.add_subparsers(
        dest="command_name", required=True,
        metavar="{init,doctor,run,demo,ui,grammar,generators,results,runs,replay,export}")

    s = sub.add_parser("init", help="create spreadex.yaml in this project")
    s.add_argument("directory", nargs="?", help="project root (default: .)")
    s.add_argument("--command", nargs="+", help="SUT command, e.g. --command java -jar sut.jar '{input}'")
    s.add_argument("--grammar", default=None,
                   help="your grammar file (default in the template: grammar.g4, to replace)")
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

    s = sub.add_parser("example", help="write a bundled example project (e.g. rhino) into its own folder")
    s.add_argument("name", help="the example: rhino")
    s.add_argument("directory", nargs="?", help="where to write it (default: ./spreadex-<name>)")
    s.add_argument("--force", action="store_true", help="restore missing files in an existing folder")
    s.set_defaults(func=cmd_example)

    s = sub.add_parser("demo", help="write a small demo project and run a real campaign in it")
    s.add_argument("directory", nargs="?", default="spreadex-demo",
                   help="where to write it (default: ./spreadex-demo)")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing demo directory")
    s.add_argument("--no-run", action="store_true",
                   help="write the project but do not run the campaign")
    s.add_argument("--jobs", type=int, default=4, help="parallel executions")
    s.add_argument("--ui", action="store_true",
                   help="when it is done, open the Workbench on the demo so its results are in front of you")
    s.add_argument("--port", type=int, default=None, help="port for --ui (default: a free one)")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("ui", help="browse this project's campaigns in a local browser UI")
    s.add_argument("--port", type=int, default=None,
                   help="use this port (default: this project's own, or the next free one)")
    s.add_argument("--list", action="store_true", help="show the Workbenches that are running")
    s.add_argument("--stop", action="store_true", help="stop this project's Workbench")
    s.add_argument("--host", default="127.0.0.1",
                   help="interface to bind (default: loopback only)")
    s.add_argument("--no-open", action="store_true", help="do not open a browser")
    s.add_argument("-v", "--verbose", action="store_true", help="log every request")
    s.add_argument("--read-only", action="store_true",
                   help="refuse every change: the UI can then only look at finished runs")
    s.add_argument("--new-token", action="store_true",
                   help="rotate this project's UI token, invalidating saved links")
    s.add_argument("--experimental", action="store_true",
                   help="enable the grammar assistant, which sends grammar context to "
                        "a model provider you configure")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("grammar", help="check a grammar, or derive each generator's dialect")
    s.add_argument("--start", help="start symbol (default: <start>, else the first rule)")
    s.add_argument("-g", "--generators", nargs="+",
                   help="generators to consider (default: all)")
    gsub2 = s.add_subparsers(dest="grammar_action", required=True)
    gc = gsub2.add_parser("check", help="diagnose a grammar and report generator support")
    gc.add_argument("source")
    gc.set_defaults(func=cmd_grammar)
    ga = gsub2.add_parser("adapt", help="write one grammar per generator dialect")
    ga.add_argument("source")
    ga.add_argument("-o", "--out", help="output directory (default: .)")
    ga.set_defaults(func=cmd_grammar)
    s.set_defaults(func=cmd_grammar)

    s = sub.add_parser("generators", help="list or install input generators")
    gsub = s.add_subparsers(dest="generators_action", required=True)
    gl = gsub.add_parser("list", help="show which generators are available")
    gl.set_defaults(func=cmd_generators)
    # "status" is what people type when they want to know what is installed.
    gs = gsub.add_parser("status", help="alias for `list`")
    gs.set_defaults(func=cmd_generators, generators_action="list")
    gi = gsub.add_parser("install", help="install generators into isolated environments")
    gi.add_argument("ids", nargs="+")
    gi.add_argument("--upgrade", action="store_true")
    gi.set_defaults(func=cmd_generators)
    s.set_defaults(func=cmd_generators)

    s = sub.add_parser("runtimes", help="list or install pinned runtimes an example needs (e.g. Rhino)")
    rsub = s.add_subparsers(dest="action")
    rsub.add_parser("list", help="list pinned runtimes").set_defaults(func=cmd_runtimes)
    ri = rsub.add_parser("install", help="download and verify a pinned runtime")
    ri.add_argument("names", nargs="+")
    ri.set_defaults(func=cmd_runtimes)
    s.set_defaults(func=cmd_runtimes)

    s = sub.add_parser("results", help="how the last campaign went")
    s.add_argument("run_id", nargs="?", help="a specific campaign (default: the latest)")
    s.add_argument("--all", action="store_true", help="list every campaign instead")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_results)

    # `report` was the name before v0.1. Kept working, kept out of the help, so
    # nobody's notes and nobody's scripts break over a rename.
    s = sub.add_parser("report")  # no help=: registered, but not advertised
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_results, all=True, run_id=None)

    s = sub.add_parser("runs", help="list, cancel or delete past campaigns")
    rsub = s.add_subparsers(dest="runs_action")
    rsub.add_parser("list", help="every campaign, newest first").set_defaults(func=cmd_runs)
    rc = rsub.add_parser("cancel", help="stop a running campaign after its current input")
    rc.add_argument("run_id")
    rc.set_defaults(func=cmd_runs)
    rd = rsub.add_parser("delete", help="permanently delete a campaign and reclaim its storage")
    rd.add_argument("run_id")
    rd.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    rd.set_defaults(func=cmd_runs)
    s.set_defaults(func=cmd_runs)

    s = sub.add_parser("record", help="save one generator's inputs from a past run, to replay without regenerating")
    s.add_argument("run_id")
    s.add_argument("generator")
    s.add_argument("-o", "--output", required=True, help="a new folder for the recording")
    s.add_argument("--suffix", default=".txt", help="file extension for the saved inputs (default .txt)")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("replay", help="inspect or re-run a past campaign")
    s.add_argument("run_id", nargs="?")
    s.add_argument("--execute", action="store_true", help="actually re-run it")
    s.add_argument("--force", action="store_true", help="replay even if the config changed")
    s.set_defaults(func=cmd_replay)

    s = sub.add_parser("export", help="export a campaign as a zip")
    s.add_argument("run_id", nargs="?",
                   help="a campaign id, or just the .zip to write (default: the latest)")
    s.add_argument("-o", "--output", help="where to write it")
    s.set_defaults(func=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        # `spreadex` on its own opens this project's Workbench -- the whole
        # point is that a developer need remember one word. In a pipe or a CI
        # job, though, a server and a browser would hang the run, so a
        # non-interactive caller gets the command list instead.
        if sys.stdout.isatty():
            argv = ["ui"]
        else:
            parser.print_help()
            return 0

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
