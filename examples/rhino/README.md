# Example: Rhino (the golden pipeline)

The full architecture end to end: **JavaScript grammar → three generators →
Cluster Coverage → SpreadEx prioritization → Rhino → verdicts.**

## Setup

Rhino is a Java project, so this example needs a JDK and a Rhino build:

```bash
git clone https://github.com/mozilla/rhino && cd rhino && ./gradlew jar
export RHINO_JAR=$PWD/rhino-all/build/libs/rhino-all-*.jar
```

Then install the generators (each into its own isolated environment):

```bash
spreadex generators install fuzzingbook fandango isla
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
    ✓ isla           directly
    - grammarinator  SpreadEx cannot emit this dialect yet
```

Derived grammars are cached in `.spreadex/cache/grammars/`, keyed by the
source's content, so editing the grammar re-derives them and nothing else does.

To see the conversion without running a campaign:

```bash
spreadex grammar adapt grammars/rhino.bnf -o /tmp/derived
```

A source using EBNF is more interesting, because FuzzingBook and ISLa have no
operators at all. `tests/fixtures/grammars/rhino.fan` uses `{1,4}`, `(...)*`,
`?` and regex terminals; adapting it desugars every one of them and expands the
regex terminals into rules.
