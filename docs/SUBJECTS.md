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
| **rhino** | ✓ **works from clean** (2026-10-05) | a Rhino jar in `RHINO_JAR`, and `spreadex generators install isla` | Full pipeline verified end to end — see below. `tests/test_rhino_example.py` skips without `RHINO_JAR`. The other four ClusGram subjects are verified too; see the section below. |

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

## ClusGram subjects

All five ICST 2026 subjects are wired and verified, 2026-10-05, each with a
campaign run end to end. **We distribute the configuration, never the system
under test** — every one points at a build you supply through an environment
variable.

| Subject | Status | Run | Needs |
|---|---|---|---|
| **rhino** | ✓ works | 251 executed · 25 ok · 226 rejected · 0 crashes | `RHINO_JAR` |
| **nashorn** | ✓ works | 81 executed · 8 ok · 73 rejected · 0 crashes | `NASHORN_SUT` |
| **graaljs** | ✓ works | 61 executed · 8 ok · 53 rejected · 0 crashes | `GRAALJS_JARS` |
| **karatejs** | ✓ works | 158 executed · 16 ok · 142 rejected · 0 crashes | `KARATE_JARS`, plus one `javac` for the harness |
| **basic** | ✓ works | 160 executed · **1 real bug** · 0 false crashes | `BASIC_CLASSES` (non-commercial licence — you compile it) |
| **rhino-vs-graaljs** | ✓ works | 55 executed · 50 mutual rejections · 0 divergences | both JS engines above |
| **CALC** | — dropped | — | superseded by the demo SUT we own, which has a documented defect and a licence |

Each lives in `examples/<name>/` with a README giving the exact command.

### One grammar, three engines

`examples/grammars/javascript.bnf` drives rhino, nashorn and graaljs — and
SpreadEx derives four generator dialects from it. Rewriting JavaScript once
per engine is the work this tool exists to remove, so the examples do not do
it either.

`karatejs` is the exception and earns it: Karate's subset has `console.log`
rather than `print`. One rule of difference is a separate language, and
feeding it the other grammar measures the grammar instead of the engine.

### What the BASIC run found

A genuine, unreported defect in JavaBASIC:

```
java.lang.ArrayIndexOutOfBoundsException: Index 256 out of bounds for length 256
	at basic.LexicalTokenizer.reset(LexicalTokenizer.java:84)
```

`reset()` copies a source line into a fixed 256-character buffer with no
bounds check. Any line longer than 255 characters overflows it — verified by
hand at 252 (fine) and 262 (throws). The campaign reached it at input 3 of 160.

**And the first run of that example reported 126 crashes, of which 125 were
not crashes at all.** They were programs jumping to an undefined line number,
which JavaBASIC diagnoses perfectly well as `Runtime Error: GOTO non-existent
line 80` — a wording missing from `rejection_patterns`. Adding it took the
report from 127 crashes across 2 signatures to 3 crashes across 1.

That is the whole argument for the oracle being configurable and for
`crash_patterns` being checked first, in one subject: BASIC *catches* the
overflow itself, prints `Caught an Exception :` and still exits 0, so neither
the exit code nor the rejection rules would have found the real one.

### Equal count or equal time

Every run in the table above used `generation: {count: N}` — the same number
of inputs from each generator, which is what the ICST 2026 experiments did and
what makes a result reproducible. It is **not** resource-fair, and on this
project's own JavaScript grammar the difference is not subtle:

| | equal count (150 each) | equal time (30 s each) |
|---|---|---|
| grammarinator | CC 0.63 — **worst** | CC 0.91, 20,000 inputs, 1,701/s — **best** |
| fuzzingbook | CC 0.71 — **best** | CC 0.22, 358 inputs, 11.9/s — **worst** |
| fandango | CC 0.70 | CC 0.56, 2,117 inputs, 69.9/s |
| isla | CC 0.70 | produced **nothing** in 30 s |

**The ranking inverts.** Under equal counts FuzzingBook looks best and
Grammarinator worst; under equal time it is the other way round by a wide
margin, and ISLa cannot deliver at that budget at all. Any claim about which
generator deserves budget has to say which basis it used, so the campaign
report now states it on every run.

Equal time is not simply the correct answer either. CC is pool-relative, and
under equal time Grammarinator supplied **89% of the pooled inputs** — a
generator contributing most of the pool touches most of the clusters almost by
construction, so part of that 0.91 is throughput rather than diversity. The
report says so when it happens. Separating the two properly is a research
question, not a config flag, and belongs with R4.

### Still open

1. **A pack format** (see `docs/PACKS.md`) so adding a subject never means
   editing core. These six are plain `spreadex.yaml` files, which works but
   does not scale to a catalogue.
2. **BASIC's licence** blocks distribution, not merely bundling. Unchanged,
   and not ours to fix.
3. **Longer budgets.** Every run above was minutes, not hours. No crashes in
   four mature JS engines is the expected outcome at that scale, not evidence
   they are defect-free.
4. **The diversity map is the limit on campaign size**, not the generators.
   Affinity Propagation needs ~6 GB at 10,000 pooled inputs and fails rather
   than degrades beyond that; see [SCALE.md](SCALE.md). Equal-time generation
   reaches 20,000 inputs in twenty seconds, so the two are not currently in
   balance.
