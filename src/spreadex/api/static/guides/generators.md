# Generators

## What this step does

Step 3 chooses **who writes your test inputs**. Each generator turns the grammar from step 2 into concrete inputs in its own way. With several generators selected, SpreadEx can later compare them by **Cluster Coverage** and spend the execution budget on the most varied inputs.

{{img:generators-cards}}

## Your options

### The generator cards

Each card shows the generator's family, whether it is ready, and the paper or project behind it. Tick a card to use it; click it for its options.

:::options
- **Recommended**: up to three generators that can run your grammar.
- **Installed**: ready in its own isolated environment.
- **Installs when you run**: selected but not installed yet; SpreadEx installs the pinned version before the campaign's clock starts.
- **Not installed**: available, not selected.
- **Replays a recording**: this generator's inputs come from a saved recording, not from generating in this run (see below).
- **Live generation not available**: an LLM generator whose live mode this version does not have.
:::

Filter by family: **Probabilistic**, **Constraint-based**, **Coverage-guided**, **LLM-based**. Generators SpreadEx cannot run (for example because of the grammar) are shown disabled, **with the reason**. **Coming soon** lists generators that are planned but cannot be selected (ClusGram, Nautilus, Dharma).

### The generators SpreadEx runs

| Generator | Family | Uses constraints | Notes |
|---|---|---|---|
| FuzzingBook | Probabilistic | no | fast; struggles with very large grammars |
| Fandango | Constraint-based | yes (Fandango format) | solves constraints with an evolutionary algorithm |
| ISLa | Constraint-based | yes (ISLa format) | |
| Grammarinator | Probabilistic | no | ANTLR grammars |
| Fuzz4All | LLM-based | | **replays a recording** in this version |

### Fresh and recorded inputs

:::options
- **Fresh**: the generator runs in this campaign and writes new inputs. Fandango, Grammarinator, FuzzingBook and ISLa are always fresh, with a fixed seed and a pinned version, so the same configuration gives the same inputs.
- **Recorded**: the inputs were generated earlier and saved with their checksums and provenance. Replaying gives **exactly those inputs** again; it does not generate new ones. Recorded inputs are still credited to the generator that wrote them, so Cluster Coverage compares it with the others.
:::

> [!WARN]
> Mixing fresh and recorded generators makes a working demonstration, **not a controlled comparison** of the generators: the recording was produced earlier, under different conditions. SpreadEx says so in the report, the Results Generators tab and the manifest.

Any generator's output can be recorded and replayed: `spreadex record <run> <generator> -o <folder>` saves what that generator produced in a run, and

```
generation:
  fuzz4all: {mode: recorded, corpus: recorded/fuzz4all}
```

replays it. A recording whose files do not match their checksums is refused, never silently used. There is no fallback between recorded and live modes.

### Not yet available

> [!NOTE]
> **Live Fuzz4All** (fresh LLM generation with your own provider and API key) and a **shared LLM configuration** for generators are not available yet. Fuzz4All currently only replays a recording.

## When to choose which

- Start with the **Recommended** generators; more generators give Cluster Coverage more to compare.
- Your grammar has constraints that matter (no division by zero, declared-before-use)? Include **Fandango** or **ISLa**.
- A very large grammar? Prefer **Fandango** and **Grammarinator**; FuzzingBook may be slow or fail.
- Want results you can reproduce exactly? Every fresh generator here is pinned and seeded; a recording reproduces its inputs byte for byte.

## Examples

:::tabs
::tab MiniCalc
FuzzingBook, Fandango and Grammarinator, 40 inputs each. Fandango also follows the "never divide by a literal zero" constraint. After generating, the campaign keeps the generator with the highest Cluster Coverage.
::tab Rhino
**Fandango** and **Grammarinator** generate fresh JavaScript from their prepared grammars; **Fuzz4All** replays 100 programs recorded earlier for the ClusGram study (model gpt-4.1-mini, as stated by its author). **FuzzingBook** is marked *Not recommended for this example*: its large JavaScript grammar does not work well with it.
::tab Your own program
With your own grammar, tick the recommended generators. If one is disabled, its card says why; the others still run.
:::

## Common problems

:::problem A generator fails to install
cause: Installing needs network access to PyPI, and some generators need a C compiler where no prebuilt package exists (for example FuzzingBook's `z3-solver` on Linux arm64).
fix: Check the network and run `spreadex generators install <id>` to see the full error. A failed install stops the run before it starts and says why; fix the install or remove that generator. (Only the guided MiniCalc demo continues without a generator that will not install.)
:::

:::problem "The recording ... was altered and is not used"
cause: A recorded input no longer matches its checksum.
fix: Restore the recording (for an example, use **Start fresh**), or record again with `spreadex record`.
:::

:::problem "live Fuzz4All generation is not available in this version"
cause: Fuzz4All was asked to generate fresh inputs.
fix: Use `mode: recorded` with a recording, or remove Fuzz4All for now.
:::

:::advanced Isolated, pinned environments
Each generator is installed into its own environment under the SpreadEx cache, at an exact pinned version, so the same seed gives the same inputs. Generators already installed elsewhere on your machine are **not** used unless you opt in with `SPREADEX_HOST_GENERATORS=1`, because a different version would silently change the inputs.
:::

:::advanced The recording format
A recording is a folder with `manifest.json` and an `inputs/` folder. The manifest lists every input with its SHA-256 and carries the provenance (where it came from, the model if any, notes). Replaying takes the first *N* inputs in manifest order, so the same count always gives the same inputs.
:::
