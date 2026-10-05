# Nashorn

Nashorn was removed from the JDK in 15, so this runs the standalone engine
jars on any modern JDK, through the small harness the ICST 2026 study used.

## What you need

A directory containing:

```
runner/NashornRunner.class     # the harness
engine/nashorn.jar             # plus its asm-*.jar dependencies
```

If you have the sources but not the class file:

```bash
javac -d runner runner/NashornRunner.java
```

Then:

```bash
export NASHORN_SUT=/path/to/that/directory
spreadex run
```

## What to expect

Most generated JavaScript is invalid, and Nashorn is right to refuse it. The
harness catches `Throwable`, prints `Runtime Error: ...` and exits 2, which
`oracle.rejection_patterns` recognises — so those land in
`expected_rejection`, not in the failure count. A verified run:

```
Executed 81 · Passed 8 · Rejected (expected) 73 · Crashes 0
```

An engine defect would escape the harness as a Java stack trace instead, and
`crash_patterns` catches that first so the broad rejection rule cannot hide it.

## The grammar

`../grammars/javascript.bnf` — the same file `examples/rhino` and
`examples/graaljs` use. One grammar, three engines, four generator dialects
derived from it.

## Copying this example

The grammar lives one level up, in `examples/grammars/javascript.bnf`, because
three engines share it. Copy `examples/` as a whole rather than this directory
alone, or point `grammar.source` at wherever you put the grammar.
