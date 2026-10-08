# Review & run

## What this step does

Step 5 sets the **budgets**, decides **in which order** inputs run and **which generators' inputs** run, shows a readiness check, and launches the campaign. The settings here are written to `spreadex.yaml` together with everything else; **The file that will be written** shows exactly what will be saved.

{{img:run-options}}

## Your options

### Generation budget

:::options
- **Equal time** (recommended): every generator gets the same number of seconds. This is the resource-fair comparison: it asks which generator does more with the same effort.
- **Equal count**: every generator is asked for the same number of inputs. Reproducible, but not resource-fair: the same count can cost one generator seconds and another minutes. SpreadEx reports each generator's actual output and cost.
:::

### Execution budget

:::options
- **Time limit**: stop executing after this many minutes.
- **Number of tests**: stop after this many inputs.
- **Entire corpus**: run every input, however long it takes.
:::

### Test ordering

:::options
- **SpreadEx prioritization** (recommended): the most different inputs first, from the diversity map of all generated inputs.
- **Random order**: a baseline to compare against.
:::

### Generator selection

:::options
- **All generators**: run the prioritized inputs of every generator.
- **Best generator**: keep the generator with the highest Cluster Coverage and run only its inputs.
- **Best 2 generators**: keep the two with the highest Cluster Coverage.
:::

### Advanced

:::options
- **Embedding**: how inputs are turned into vectors for clustering. **TF-IDF** needs no GPU and no key. **UniXcoder** needs the optional `spreadex[neural]` install.
- **Parallel executions**: more is faster, but makes durations noisier and can time out an input that would have passed on its own.
:::

### Ready to run

The readiness card checks **SUT** (tested), **Grammar**, **Generators**, **Strategy**, **Budget** and **Storage**, and names the step to fix for anything missing. Generators that are not installed yet are listed: they are installed **before** the campaign's clock starts. Then press **Run campaign**.

{{img:run-ready}}

## What Cluster Coverage and prioritization do, and do not, tell you

All generated inputs are pooled, turned into vectors and grouped into clusters of similar inputs: the *diversity map*.

- **Cluster Coverage (CC)** of a generator is the share of those clusters its inputs reached. It is relative to this run's pool: add or remove a generator and every score changes.
- **SpreadEx prioritization** orders the inputs so that the most different ones run first, which tends to reach different behaviour early when the budget is short.

> [!NOTE]
> Both are **heuristics for spending a budget well**. A high CC means a generator's inputs are more varied *here*; it does not predict that they find more faults, and prioritization does not guarantee that the first failures are found sooner. Use **Random order** as a baseline when you want to measure the difference.

## When to choose which

- Deciding which generator deserves budget? **Equal time**.
- Need identical runs to compare or to publish? **Equal count** (every generator is pinned and seeded).
- Limited time? **SpreadEx prioritization** with a **Time limit**.
- Many generators and a small execution budget? **Best generator** or **Best 2 generators**.

## Examples

:::tabs
::tab MiniCalc
Equal count (40 inputs each), **Best generator**: the campaign keeps the generator with the highest Cluster Coverage and executes its inputs in SpreadEx priority order.
::tab Rhino
Equal count (100 each), **Best generator**. On the reference run Fandango reaches the most clusters and is kept; its 100 programs run on Rhino. Fuzz4All's CC is computed from its replayed inputs, and the report says so.
::tab Your own program
Start with **Equal time**, a few minutes of **Time limit**, and **SpreadEx prioritization**. Compare with a **Random order** run later.
:::

## Common problems

:::problem "Not ready yet"
cause: One of the readiness rows is missing: for example the SUT was changed and not tested again.
fix: Each row says why and offers **Fix**, which opens the step to correct.
:::

:::problem "A campaign is already running"
cause: Only one campaign runs per project, whether started here, from another Workbench, or from the command line.
fix: Open it from Campaigns, or cancel it there (or with `spreadex runs cancel`).
:::

:::problem The estimate is much longer than expected
cause: With **Number of tests** or **Entire corpus**, the estimate assumes every input may use its full timeout.
fix: Use a **Time limit**, or lower the timeout in step 4.
:::

:::advanced Reproducibility
With equal count, a fixed seed, pinned generator versions and (for the Rhino example) a pinned runtime, the same configuration gives the same inputs, the same Cluster Coverage, the same selection and the same priority order. With several parallel executions the *order in which inputs finish* can vary, because a slow input finishes later; the priority order itself does not change. Every run records what it used in its manifest; see [Results](#guide/results#what-a-run-records).
:::

:::advanced How clusters are formed
Inputs are embedded (TF-IDF by default), clustered, and each generator is scored by the share of clusters its inputs fall into. The clustering's effective number of clusters (*k_eff*) and any caveats (for example a clustering that did not converge) are reported with the scores.
:::
