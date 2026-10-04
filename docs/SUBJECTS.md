# Systems under test: what actually works, and what only exists

A ✓ in this table means **someone ran it from a clean install and it worked**,
with the date and the command. It never means "there is code for it". A table
that conflates those is how a tool acquires a reputation for not working.

Last verified: 2026-10-05, macOS 15.5 (x86_64), Python 3.11, from a wheel
installed into an empty virtualenv outside this repository.

## Ships with the tool

| Subject | What it is | Status | Needs | Verified by |
|---|---|---|---|---|
| **demo (`calc.py`)** | ~100-line expression evaluator we own, one documented defect | ✓ **works from clean** | nothing beyond the wheel | `spreadex demo` — 155 inputs, 21 expected rejections, found the defect at input 23 of 155 in 59 s including the FuzzingBook install |
| **toy-parser** | corpus-only campaign, no grammar | ✓ works | nothing | `tests/test_examples_end_to_end.py` in CI on every commit |
| **differential** | two implementations, divergence oracle | ✓ works | nothing | `tests/test_examples_end_to_end.py` in CI on every commit |

## In the repository, needs something you supply

| Subject | Status | Needs | Notes |
|---|---|---|---|
| **rhino** | ⚠ **not verified from clean this session** | a Rhino jar in `RHINO_JAR`, plus FuzzingBook, ISLa and Fandango installed | The pipeline (JS grammar → 3 generators → CC → prioritization → Rhino) ran during development. Re-running it on 2026-10-05 stopped at `GeneratorError: ISLa is not installed`, which is the honest current state of a clean machine. `tests/test_rhino_example.py` skips without `RHINO_JAR`. |

## ClusGram subjects — the next layer, not v0.1

These are the ICST 2026 subjects. None is packaged, and nothing here is a
promise that it builds today.

| Subject | What it is | Status | Known blockers |
|---|---|---|---|
| **rhino** | Mozilla Rhino, JS engine (Java) | ⚠ partial, see above | needs a built jar |
| **nashorn** | Nashorn JS engine (Java) | ✗ not packaged | jars exist in the research tree; no `spreadex.yaml`, never run through this tool |
| **graaljs** | GraalJS (Java/native) | ✗ not packaged | needs a GraalVM build; the heaviest of the set |
| **karatejs** | Karate's JS subset (Java) | ✗ not packaged | grammar exists and parses; the SUT side does not |
| **basic** | a BASIC interpreter (Java) | ✗ **blocked** | **no LICENSE file**; the in-file header permits non-commercial use only, so it cannot be bundled or publicly fetched. It also needs JDK 21 and reads programs on **stdin**, which `exec/runner.py` cannot do — it only substitutes `{input}` or appends a path. Both are fixable; the licence is the one that is not ours to fix. |
| **CALC** | the research calculator | ✗ not packaged | superseded for demo purposes by the SUT we own |

### What has to happen before any of these gets a ✓

1. **stdin-driven SUTs.** `Target.render` substitutes `{input}` or appends the
   path. BASIC needs the file on stdin. Until that exists, a whole class of
   real systems cannot be tested at all.
2. **A pack format** (see `docs/PACKS.md`) so adding a subject never means
   editing core.
3. **Licence clarity for BASIC**, which blocks distribution and not merely
   bundling.
4. **A clean-machine run per subject**, recorded here with its date and
   command. Nothing moves to ✓ on the strength of code review.
