# Inputs

## What this step does

Step 2 describes **what valid test inputs look like and where they come from**. Usually that is a **grammar**: a set of rules from which generators write new inputs. If you already have inputs, you can point at a folder of them instead.

{{img:inputs-modes}}

## Your options

### Input language (optional)

Choosing a language fills in the **File extension** given to every input file when it is run, for example `.js`. Many programs choose their parser from it. Leave it empty to use none.

### Where inputs come from

:::options
- **SpreadEx grammar**: start from a tested grammar that ships with SpreadEx. Today one is bundled: *Arithmetic expressions*, the grammar behind the MiniCalc demo.
- **Provide grammar**: use a grammar file that is already in your project folder.
- **Import grammar**: bring one from elsewhere. SpreadEx reads BNF, EBNF, ANTLR (.g4), Fandango, ISLa and FuzzingBook (.py) grammars.
- **No grammar**: use inputs you already have in a folder. Generators are skipped; prioritization, execution and results work as usual.
:::

### A prepared grammar for each generator

Some projects give each generator a grammar written for it, in that generator's own format. The Rhino example does this. Step 2 then shows a table, *generator → grammar file → format*, and uses each file exactly as written. **choose one grammar** switches to the usual single-grammar flow; the prepared files stay in the project and still win for their generators.

{{img:inputs-prepared}}

### Constraints

A grammar says what an input *looks like*; a constraint says what must also be *true* of it ("never divide by a literal zero"). Fandango and ISLa can follow constraints; FuzzingBook and Grammarinator use the grammar alone. A constraint file written in Fandango's own format is passed to Fandango unchanged.

## When to choose which

- Your input language already has a grammar file? **Provide grammar** (in the project) or **Import grammar** (from elsewhere).
- Trying SpreadEx on arithmetic? **SpreadEx grammar**.
- No grammar, but a folder of real inputs (a regression corpus, crash reproducers)? **No grammar**.
- Opened the Rhino example? Keep its **prepared grammar for each generator**.

## Examples

:::tabs
::tab MiniCalc
`calc.bnf` describes numbers, `+ - * / %` and brackets. The demo also ships `spec/constraints.fan`, a Fandango constraint that never divides by a literal zero; SpreadEx hands it to Fandango unchanged, and the other generators use the grammar alone.
::tab Rhino
A grammar prepared for each generator, copied unchanged from the ClusGram research artifact:

| Generator | Grammar file | Format |
|---|---|---|
| Fandango | `grammars/fandango/rhino.fan` | Fandango, with constraints |
| Grammarinator | `grammars/grammarinator/rhino.g4` | ANTLR |
| Fuzz4All | none: it replays a recorded corpus | |

`grammars/PROVENANCE.md` lists where each file came from and its checksum.
::tab Your own program
For the JSON validator, provide a small `json.bnf` in the project:

```
<start>  ::= <value>
<value>  ::= <object> | <array> | <string> | <number> | "true" | "false" | "null"
<array>  ::= "[]" | "[" <elements> "]"
...
```

Or, with real JSON files at hand, choose **No grammar** and enter their folder.
:::

## Common problems

:::problem "The grammar has errors"
cause: The grammar does not parse, or refers to a rule that is not defined.
fix: Open **View details**, fix the listed lines, and continue. `spreadex grammar check <file>` shows the same diagnostics on the command line.
:::

:::problem A generator says it cannot express this grammar
cause: Not every generator supports every construct (for example some regular-expression features).
fix: Step 3 disables that generator and says why. Choose another generator, or simplify the rule it names.
:::

:::problem "Enter the folder that holds your inputs"
cause: **No grammar** is selected but the folder is empty or missing.
fix: Enter a folder inside the project that contains at least one input file.
:::

:::advanced One grammar, every generator's format
From a single grammar SpreadEx derives each generator's format: a FuzzingBook dictionary, BNF for ISLa, Fandango's notation and ANTLR for Grammarinator. Derived files are cached by the grammar's content. A per-generator entry in `spreadex.yaml` always wins over the shared one:

```
grammar:
  source: grammars/expr.bnf          # shared
  fandango: grammars/expr.fan        # this generator's own
```

The expressibility report on this page says, generator by generator, whether the grammar can be expressed directly, with a known approximation, or not at all.
:::

:::advanced The experimental grammar assistant
Started with `spreadex ui --experimental`, the Workbench offers an opt-in assistant that can propose a grammar from example inputs, repair a broken one, or draft constraints. It uses a model provider you choose (OpenAI or Anthropic with an API key from an environment variable, or a local Ollama). SpreadEx validates every proposal and you review it before it is used. It is not a test-input generator; see [Generators](#guide/generators#not-yet-available) for what is not available yet.
:::
