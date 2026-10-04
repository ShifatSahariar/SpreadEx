# SpreadEx

**SpreadEx is a local-first harness that runs multiple grammar-based generators against a system
under test and uses a finite budget to decide which generators and which generated inputs deserve
execution.**

Specialized fuzzers generate. SpreadEx orchestrates, measures, compares, prioritizes and
reproduces. Everything runs on your machine: your SUT, grammars, generated programs, crashes and
corpus never leave it.

The algorithms are those of the ICST 2026 paper *Embedding-based Diversity Mapping for Test
Generator Selection and Input Prioritization in Grammar-based Testing*, and a CI gate asserts
this implementation still computes them — see [docs/MIGRATION.md](docs/MIGRATION.md).

## Quick start

```bash
pip install -e .          # no torch, no pandas, no Docker, no JDK
cd examples/toy-parser
spreadex doctor           # prints fixes, not diagnoses
spreadex run
```

```
  Execution
    Executed .............. 60
    Passed ................ 40
    Rejected (expected) ... 15
    Crashes ............... 5
```

Note the third line: fifteen inputs were *correctly rejected* by the parser. A tool that counted
those as failures would report twenty bugs where there is one. Telling those apart is the oracle's
job, and it is the difference between a usable tool and a noise generator.

## Commands

| | |
|---|---|
| `spreadex init` | write `spreadex.yaml` for this project |
| `spreadex doctor` | check the setup; every problem comes with the command that fixes it |
| `spreadex generators list` / `install` | see and install generators into isolated environments |
| `spreadex run` | generate → rank → prioritize → execute → judge → persist |
| `spreadex report` | list past runs |
| `spreadex ui` | browse campaigns in a local, read-only browser UI |
| `spreadex replay <id>` | inspect a past campaign, or re-run it (`--execute`) |
| `spreadex export` | zip the manifest, results and failing inputs |

Flags: `--budget 10m`, `--selection-signal cc|random`, `-j 8`, `--fail-on new-failure` (CI).

## Generators

Installation is deterministic — a catalog of package names and pins, acted on by a package
manager. No model guesses at install commands: that would make SpreadEx less reproducible, less
secure, harder to debug and impossible to artifact-evaluate.

```
$ spreadex generators list
  ✓ Fandango         installed (1.2.0, host)          grammar: fandango-fan  constraints: yes
  ✓ FuzzingBook      installed (1.2.2, environment)   grammar: fuzzingbook-dict
  ✓ Grammarinator    installed (26.1, host)           grammar: antlr4
  ✓ ISLa             installed (1.14.4, environment)  grammar: bnf  constraints: yes
```

Each generator gets its own environment under `~/.cache/spreadex/generators/`, so one
generator's pins cannot break another's — or SpreadEx itself. ISLa, for instance, needs
`setuptools<81` to import at all; that pin is recorded in the catalog and confined to its own
environment. `spreadex run` never installs anything implicitly: it reports what is missing and
names the command that fixes it.

## The golden pipeline

[`examples/rhino`](examples/rhino) runs the whole architecture against a real
JavaScript engine: three generators → Cluster Coverage → SpreadEx
prioritization → Rhino → verdicts.

```
  Cluster coverage  (k_eff=43)
    fandango              0.63  ###################
    fuzzingbook           0.37  ###########
    isla                  0.21  ######

  Execution
    Executed .............. 308
    Passed ................ 32
    Rejected (expected) ... 276
    Crashes ............... 0
```

Cluster coverage is computed **before anything is executed** — that is the point
of the signal. Here it says Fandango reaches roughly twice as much of the input
space as FuzzingBook and three times as much as ISLa, which is what a budget
allocator needs to know.

The 276 rejections matter as much as the crash count. Rhino exits `3` both for a
program it refused to parse and for an engine crash, so the exit code cannot
separate them. `oracle.rejection_patterns` and `crash_patterns` do. Getting this
wrong is not a theoretical risk: an earlier, narrower pattern list reported 15
programs that merely did `throw new TypeError(...)` as engine crashes.

## One grammar, every dialect

Generators speak different notations: FuzzingBook wants a Python dict, ISLa
plain BNF, Fandango BNF with EBNF operators and regex terminals. Testing one
system with several of them has meant maintaining several grammars by hand and
keeping them in step. SpreadEx derives them from one source.

```yaml
grammar:
  source: grammars/rhino.bnf     # one file; every dialect comes from it
```

```bash
spreadex grammar check grammars/rhino.bnf   # diagnose, and see what each generator supports
spreadex grammar adapt grammars/rhino.bnf -o out/
```

Deriving is a real conversion, not a copy. For dialects with no operators,
`(", " <item>)*` becomes right-recursive helper rules and `r'[A-Za-z]{1,2}'`
becomes a shared character-class rule. Anything a generator genuinely cannot
express is reported and that generator is skipped, rather than being handed a
grammar it will choke on.

**ANTLRv4 works in both directions.** A `.g4` can be the source — so a grammar
from the ANTLR zoo drives every generator — and SpreadEx emits `.g4`, which is
what Grammarinator consumes.

| | BNF/EBNF | FuzzingBook | ANTLRv4 |
|---|---|---|---|
| **read** | yes | yes | yes |
| **write** | yes (ISLa, Fandango) | yes | yes (Grammarinator) |

Reading ANTLR for *generation* ignores what only matters for parsing: actions,
semantic predicates, labels and lexer commands. Each is counted and reported,
because a dropped predicate means generated inputs may violate a condition the
grammar's author was enforcing. `.` and `~[...]` describe sets by exclusion,
which is unbounded when generating, so they expand against a documented
printable alphabet and say so.

`spreadex grammar check` reports what a generator will not tell you until the
campaign has already run: undefined and unreachable rules, rules that can never
terminate, left recursion (with the cycle), ambiguity, and per-generator
expressibility.

```
  Generator support
    ✓ fandango       directly
    ✓ fuzzingbook    after rewriting (bounded repetition ({m,n}), grouping, regex terminal, ...)
    ✓ isla           after rewriting (...)
      ! <IDENT_NUM> and <IDENT_STR> derive the same language; ISLa may reject this at solve time
    - grammarinator  SpreadEx cannot emit this dialect yet
```

## The UI

```bash
spreadex ui
```

Prints a tokenized `http://127.0.0.1:…` URL and opens it. Four views, each tied
to a decision rather than to a metric that looked nice:

- **Generator comparison** — cluster coverage beside input count and generation
  cost, so a coverage number is never read without its price.
- **Budget curve** — distinct failure signatures against inputs executed, with
  the same inputs in random order as a dashed line. The gap is what the
  ordering bought, and no gap is a real answer too.
- **Failure signatures** — the stderr that produced each one, and the input
  that triggers it.
- **Grammar** — diagnostics and what each generator can express, before a
  budget is spent finding out.

It is **read-only**: the UI reads `.spreadex/` and never starts, stops or
changes a campaign, which keeps the browser out of the trust path for anything
that executes code. It is also stdlib-only, so it needs no extra install, and
its Content-Security-Policy forbids loading anything off-machine.

A localhost bind is not an authentication boundary — any page you visit can
POST to 127.0.0.1, and DNS rebinding defeats naive Origin checks. So: a random
per-session token on every API request, and strict `Host` validation, which is
what actually stops rebinding. The server runs in the foreground, so it cannot
be orphaned and there is never a question of which instance you are looking at.

## Selection signals

```
Selection signal        Prioritization
────────────────        ──────────────
Cluster Coverage  ──►   SpreadEx
(default)
k-path [planned]  ──►   SpreadEx
```

Cluster Coverage is one `SelectionSignal` implementation, not the architecture. Ordinary use
needs no choice; `--selection-signal` exists for experiments.

The diversity map is one object with two readouts: clustering the union of every generator's
inputs gives per-generator Cluster Coverage (which allocates *generation* budget) and a
prioritized stream over that union (which allocates *execution* budget).

## How it works

```
Generate → Validate → Signals → Prioritize → Execute → Observe → Oracle → Persist
                                                                            │
                                                                     .spreadex/corpus.db
```

**An `Observation` is a measurement; only an `Oracle` decides what it means.** Verdicts are
`ok`, `expected_rejection`, `crash`, `timeout` and `divergence`.

SpreadEx reports failure **signatures**, never "unique bugs" — stack-hash heuristics have been
measured inflating bug counts by an order of magnitude
([Igor, CCS'21](https://hexhive.epfl.ch/publications/files/21CCS.pdf)).

## Local-first

```
my-project/
├── spreadex.yaml
└── .spreadex/
    ├── corpus.db          # SQLite metadata
    ├── blobs/             # content-addressed inputs, stored once
    ├── runs/<id>/         # manifest.json, results.jsonl, logs/
    └── cache/
```

Inputs are content-addressed, so the same program from two generators executed against two SUT
versions is one blob with four execution rows.

## Status

**v0.1.0-alpha.** Working: execution plane, corpus store, campaign manager, selection signals,
crash/timeout/differential oracles, per-SUT rejection and crash patterns, manifest and replay,
deterministic generator installation, generator adapters for FuzzingBook, Fandango and ISLa, and
the golden Rhino pipeline end to end.

Also working: the grammar adapter — one source grammar, every generator's dialect derived, with
diagnostics and per-generator expressibility.

All four Tier-1 generators now run: FuzzingBook, Fandango, ISLa and Grammarinator.

Not yet: coverage collection, regression mode, adaptive allocation.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q -m "not network" --ignore=tests/golden

# The gate, against the research repository:
pip install -e ".[golden]"
SPREADEX_REQUIRE_GOLDEN=1 pytest tests/golden -q
```
