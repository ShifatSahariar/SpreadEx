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
crash/timeout/differential oracles, manifest and replay, deterministic generator installation,
CI-friendly exit codes.

Not yet: generator *adapters* (the manager installs them; wiring them into generation is next),
the grammar adapter, coverage collection, the browser UI, regression mode, adaptive allocation.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q -m "not network" --ignore=tests/golden

# The gate, against the research repository:
pip install -e ".[golden]"
SPREADEX_REQUIRE_GOLDEN=1 pytest tests/golden -q
```
