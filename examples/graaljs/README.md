# GraalJS

Runs GraalJS from its standalone runtime jars on an ordinary JDK — no GraalVM
installation required.

```bash
export GRAALJS_JARS=/path/to/graaljs/runtime/jars   # graaljs.jar, graal-sdk.jar, truffle-api.jar, ...
spreadex run
```

On a real GraalVM, replace the command in `spreadex.yaml` with
`["js", "{input}"]`.

## The banner, and why it is switched off

Without these two system properties GraalJS prints **seventeen lines of
warning on every run**, including successful ones — the Truffle attach notice
and the interpreter-only notice:

```
-Dpolyglotimpl.AttachLibraryFailureAction=ignore
-Dpolyglot.engine.WarnInterpreterOnly=false
```

They are silenced at the source rather than filtered afterwards. In a
differential campaign (see `examples/rhino-vs-graaljs`) that banner is stderr
the two engines would have to agree on, and it would make every single input
look like a divergence.

## What to expect

GraalJS exits 7 for a script it refused and names the error type on stderr.
A verified run:

```
Executed 61 · Passed 8 · Rejected (expected) 53 · Crashes 0
```

## Copying this example

The grammar lives one level up, in `examples/grammars/javascript.bnf`, because
three engines share it. Copy `examples/` as a whole rather than this directory
alone, or point `grammar.source` at wherever you put the grammar.
