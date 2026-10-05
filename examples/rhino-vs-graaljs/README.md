# Rhino vs GraalJS — differential testing

Two independent JavaScript engines, the same input, **no expected output
needed**. This is the cheapest high-value oracle there is: you do not have to
know what a generated program should print, only that two mature
implementations should agree.

```bash
export RHINO_JAR=/path/to/rhino-all-*.jar
export GRAALJS_JARS=/path/to/graaljs/runtime/jars
spreadex run
```

## What counts as a divergence

Not this: both engines refuse the program. They word syntax errors
differently and Rhino exits 3 where GraalJS exits 7 — the oracle compares the
*class* of the exit code for exactly that reason, and mutual rejection is
reported as agreement.

This: one engine accepts what the other refuses, or both accept and print
different things. Either is a genuine disagreement between implementations
and worth a look.

## What to expect

A verified run:

```
Executed 55 · Passed 5 · Rejected (expected) 50 · Divergences 0
```

Fifty mutual rejections, correctly reported as agreement rather than fifty
findings. Zero divergences means these two engines agreed on everything this
budget reached — a real result, not a missing measurement.

## Copying this example

The grammar lives one level up, in `examples/grammars/javascript.bnf`, because
three engines share it. Copy `examples/` as a whole rather than this directory
alone, or point `grammar.source` at wherever you put the grammar.
