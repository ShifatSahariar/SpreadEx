# Systems under test: what actually works, and what only exists

A ✓ in this table means **someone ran it from a clean install and it worked**,
with the date and the command. It never means "there is code for it". A table
that conflates those is how a tool acquires a reputation for not working.

Last verified: 2026-10-05, macOS 15.5 (x86_64), Python 3.11, JDK 21.0.2, from
a wheel installed into an empty virtualenv outside this repository.

## Ships with the tool

| Subject | What it is | Status | Needs | Verified by |
|---|---|---|---|---|
| **demo (`calc.py`)** | ~100-line expression evaluator we own, one documented defect | ✓ **works from clean** | nothing beyond the wheel | `spreadex demo` — 155 inputs, 21 expected rejections, found the defect at input 23 of 155 in 59 s including the FuzzingBook install |
| **toy-parser** | corpus-only campaign, no grammar | ✓ works | nothing | `tests/test_examples_end_to_end.py` in CI on every commit |
| **differential** | two implementations, divergence oracle | ✓ works | nothing | `tests/test_examples_end_to_end.py` in CI on every commit |

## In the repository, needs something you supply

| Subject | Status | Needs | Notes |
|---|---|---|---|
| **rhino** | ✓ **works from clean** (2026-10-05) | a Rhino jar in `RHINO_JAR`, and `spreadex generators install isla` | Full pipeline verified end to end — see below. `tests/test_rhino_example.py` skips without `RHINO_JAR`. |

### The Rhino run, in full

Rhino 1.8.1-SNAPSHOT, JDK 21.0.2, macOS 15.5, from the clean wheel:

```
grammar: derived 4 dialect(s) from rhino.bnf
  fuzzingbook    150 inputs in 12.9s
  fandango       150 inputs in  2.5s
  isla           150 inputs in 44.8s
  grammarinator  150 inputs in  2.9s
600 generated -> 588 valid, unique
cluster coverage: fuzzingbook 0.71, fandango 0.70, isla 0.70, grammarinator 0.63  (k_eff=82)
Executed 251 of 588 before the 180s execution budget ran out
  Passed 25 · Rejected (expected) 226 · Crashes 0 · Timeouts 0
```

**One grammar drove four generators**, each in its own dialect, and all four
produced inputs. Three facts worth stating plainly:

- **226 of 251 inputs were rejected by Rhino, and none of that is a finding.**
  Exit code 3 covers both "I refused your script" and "I broke", so the exit
  code cannot separate them — the `^js: ` rejection pattern does. Without it
  this run would have reported 226 crashes and zero of them real. This is the
  whole reason Testing Strategy is a wizard step.
- **No crashes.** Rhino 1.8.1 is mature and a 3-minute budget on a generic
  JavaScript grammar is not going to break it. That is the expected outcome,
  not a missing measurement.
- **Generation costs differ by 18×** (Fandango 2.5s, ISLa 44.8s for the same
  150 inputs), so those CC values compare equal *input counts* and not equal
  *budgets*. The tool says so in its own output; it is the sharpest open
  question about comparing generators this way.

Two things this run corrected in our own documentation:

- **ISLa does scale to this grammar.** An earlier note said it exceeded a 60s
  budget; that was on the ANTLR `rhino.g4` path. On `rhino.bnf` it produced
  150 inputs in 44.8s.
- **Grammarinator generates.** `doctor` claimed "generation is not wired up in
  v0.1" from a hardcoded list that went stale when ANTLR support landed. It
  produced 142 unique inputs. The hardcoded list is gone.

## ClusGram subjects — the next layer, not v0.1

These are the ICST 2026 subjects. None is packaged, and nothing here is a
promise that it builds today.

| Subject | What it is | Status | Known blockers |
|---|---|---|---|
| **rhino** | Mozilla Rhino, JS engine (Java) | ✓ verified, see above | a built jar (not distributable by us) |
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
