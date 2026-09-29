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

## Grammars

`grammars/` holds one grammar per dialect, taken from the ICST 2026 replication
package. They describe the same language; a grammar adapter that derives them
from a single source is a later phase.
