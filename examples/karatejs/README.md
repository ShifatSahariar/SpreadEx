# Karate's JavaScript engine

`karate-js` is the JS engine inside [Karate](https://github.com/karatelabs/karate).
Its JavaScript is a *subset*, which is why this example has its own grammar.

## You have to build the harness

Karate ships `io.karatelabs.js.JsLauncher`, but it catches the exception,
prints a stack trace and **exits 0 anyway**. For a campaign that is useless: a
script the engine refused looks exactly like one it ran, so every input would
be reported as a pass and the run would look perfect while telling you
nothing.

`KarateRunner.java` in this directory does what the ICST 2026 study's
`NashornRunner` does — reports the refusal in one line and exits non-zero:

```bash
export KARATE_JARS=/path/to/karate-v2/karate-js/target
mkdir -p build
javac -cp "$KARATE_JARS/karate-js-2.0.0.RC1.jar" -d build KarateRunner.java
export KARATE_RUNNER=$PWD/build
spreadex run
```

| exit | meaning | verdict |
|---|---|---|
| 0 | the script ran | `ok` |
| 2 | the engine refused it, or it threw | `expected_rejection` |
| 1 | the harness itself could not run | a real problem |

`StackOverflowError` and `OutOfMemoryError` are deliberately *not* caught, so
an engine-level failure still escapes as the Java stack trace it is.

## Its own grammar

`karatejs.bnf` is identical to `../grammars/javascript.bnf` except for one
rule: Karate's subset has `console.log` and not Rhino's `print`. One line of
difference earns a whole separate grammar because it is a separate language —
using the other one here produces programs Karate refuses on sight, which
measures the grammar rather than the engine.

## What to expect

A verified run:

```
Executed 158 · Passed 16 · Rejected (expected) 142 · Crashes 0
```
