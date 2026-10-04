# Verified Packs

A **pack** is everything needed to test one system: where to get it, how to
run it, how it reports input it refuses, and a grammar to drive it. The point
is that adding a subject is adding a file, never editing the engine.

**Status: designed, not built.** This document is the schema and the
rationale. v0.1 ships the generator catalog, which is already pack-shaped
(`src/spreadex/generators/catalog/*.yaml`); SUT packs follow the same pattern
for the same reason.

## Why

Today a new subject means a hand-written `spreadex.yaml`, a grammar found
somewhere, and a rejection pattern worked out by running the thing and reading
its stderr. That last step is the one people get wrong, and getting it wrong
means every invalid input is reported as a crash. A pack carries the answer.

## Schema

```yaml
# pack.yaml
name: rhino
version: 1.8.1
description: Mozilla Rhino, a JavaScript engine for the JVM.
license: Apache-2.0          # the SUBJECT's licence; required, never guessed

requires:
  java: ">=11"               # checked by `spreadex doctor` before anything runs

acquire:                     # how to get it; never run implicitly
  kind: download
  url: https://repo1.maven.org/.../rhino-1.8.1.jar
  sha256: "..."              # mandatory. No checksum, no pack.

run:
  command: ["java", "-jar", "{pack}/rhino.jar", "{input}"]
  timeout: 10s
  # input_mode: file | stdin   -- stdin is NOT implemented yet (see SUBJECTS.md)

oracle:
  type: crash
  rejection_patterns:        # how this system says "I refused that"
    - "^js: SyntaxError"
  crash_patterns:            # checked FIRST, so a broad rejection rule
    - "java.lang.NullPointerException"   # cannot mask a real bug

grammar:
  source: grammars/javascript.bnf
  start: start
```

## Rules

- **A checksum is mandatory.** A pack that downloads something unverified is a
  supply-chain hole with a friendly name.
- **Acquisition is explicit.** `spreadex packs install rhino`, never a side
  effect of `spreadex run`. The same rule the generator catalog already
  follows.
- **The licence field is required and is the subject's**, not ours. BASIC is
  the worked example of why: no LICENSE file, non-commercial terms in a source
  header, and therefore not distributable regardless of how convenient it
  would be.
- **`rejection_patterns` is the point.** A pack whose author did not work out
  how the system reports bad input is not finished, because the first campaign
  will report thousands of findings and none of them real.
- **A pack is verified or it is not published.** Same bar as
  [SUBJECTS.md](SUBJECTS.md): someone ran it from clean, on a date, with a
  command.

## Open questions

- Where do packs live? A directory in the user's project is enough to start.
  A central index is a maintenance commitment, and the graveyard of fuzzing
  infrastructure is mostly central indexes nobody funded past year three.
- Does a pack pin a grammar version separately from the SUT version? Grammars
  rot on a different schedule than the systems they describe, so probably yes.
