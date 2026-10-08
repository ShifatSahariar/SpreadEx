# Rhino showcase

A real JavaScript engine tested end to end: three generators write JavaScript, SpreadEx compares
them by **Cluster Coverage**, keeps the best one, prioritizes its inputs and runs them on Rhino.

```bash
spreadex runtimes install rhino                    # public Rhino 1.9.1, SHA-256 verified
spreadex generators install fandango grammarinator
spreadex doctor
spreadex run
```

Needs Java 11 or newer.

## What runs

| Generator | Inputs | How |
|---|---|---|
| Fandango | generated in this run | `grammars/fandango/rhino.fan` |
| Grammarinator | generated in this run | `grammars/grammarinator/rhino.g4` |
| Fuzz4All | **replayed** from `recorded/fuzz4all/` | generated earlier with an LLM (gpt-4.1-mini) for the ClusGram study |

Each generator is asked for the same number of inputs (`generation.count`); the campaign reports
how many each actually produced. Fuzz4All's inputs are a saved corpus: replaying it reproduces
those exact inputs, but it is not a fresh LLM run, and an LLM would not regenerate them
identically. **This is a demonstration of the pipeline, not a controlled comparison of the
generators.**

## Which Rhino

The public **Rhino 1.9.1** release from Maven Central (MPL 2.0), run through its standard shell
(`org.mozilla.javascript.tools.shell.Main`). The ClusGram and ICST studies used a patched Rhino
1.8.1 snapshot and their own harness, so results here are not those studies' numbers.

Grammars and the recorded corpus are copied unchanged from ClusGram; `grammars/PROVENANCE.md`
lists every source file and checksum.
