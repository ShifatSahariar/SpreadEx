# Example: Rhino (the golden pipeline)

The full architecture end to end: **one JavaScript grammar → four generators →
Cluster Coverage → SpreadEx prioritization → Rhino → verdicts.**

## Setup

Rhino is a Java project, so this example needs a JDK and a Rhino build:

```bash
git clone https://github.com/mozilla/rhino && cd rhino && ./gradlew jar
export RHINO_JAR=$PWD/rhino-all/build/libs/rhino-all-*.jar
```

Then install the generators (each into its own isolated environment):

```bash
spreadex generators install fuzzingbook fandango isla grammarinator
```

## Run

```bash
spreadex doctor
spreadex run -j 4
```

## What to look for

`Cluster coverage` reports how much of the shared diversity map each generator
reached. That is the signal deciding which generator deserves generation
budget, and it is computed before anything is executed.

Most generated programs are *invalid JavaScript*, and Rhino is right to refuse
them. Those appear as `Rejected (expected)`, not as bugs. Rhino exits 3 either
way, so the `rejection_patterns` in `spreadex.yaml` are what separate "the
engine refused this script" from "the engine broke" — without them every
invalid program would be reported as a crash.

## One grammar, three dialects

`grammars/rhino.bnf` is the only grammar here. SpreadEx derives what each
generator needs from it:

```
$ spreadex grammar check grammars/rhino.bnf
  57 rules, start <start>
  uses: plain BNF

  Generator support
    ✓ fandango       directly
    ✓ fuzzingbook    directly
    ✓ grammarinator  directly
    ✓ isla           directly
```

Four generators, four notations — a FuzzingBook dict, plain BNF for ISLa,
BNF-with-operators for Fandango, and ANTLRv4 for Grammarinator — all from the
one file.

Derived grammars are cached in `.spreadex/cache/grammars/`, keyed by the
source's content, so editing the grammar re-derives them and nothing else does.

To see the conversion without running a campaign:

```bash
spreadex grammar adapt grammars/rhino.bnf -o /tmp/derived
```

Other notations work as sources too. `tests/fixtures/grammars/rhino.fan` uses
`{1,4}`, `(...)*`, `?` and regex terminals, all of which are desugared for the
generators that have no operators. `tests/fixtures/grammars/rhino.g4` is a far
richer ANTLR grammar of near-complete JavaScript — from it Fandango and
Grammarinator generate in seconds, while FuzzingBook and ISLa struggle, which
the budget reports rather than hides.

## Copying this example

The grammar lives one level up, in `examples/grammars/javascript.bnf`, because
three engines share it. Copy `examples/` as a whole rather than this directory
alone, or point `grammar.source` at wherever you put the grammar.
