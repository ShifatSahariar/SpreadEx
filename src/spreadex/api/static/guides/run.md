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

### Diversity map

The **Diversity map** choice appears with SpreadEx prioritization. It decides how inputs become vectors before clustering; Cluster Coverage and the ordering both come from this one map.

:::options
- **UniXcoder** (recommended, default): a code model evaluated in the SpreadEx study, run on this machine. Needs `pip install 'spreadex[neural]'`; the first campaign downloads the model (506 MB, once) into the Hugging Face cache.
- **OpenAI**: `text-embedding-3-small`, the model behind the study's prioritization results. Sends every generated input to OpenAI and is billed to the key in `OPENAI_API_KEY`, which SpreadEx reads from the environment and never stores.
- **TF-IDF**: character n-grams. No download and no key; not evaluated for fault detection.
:::

If the chosen model cannot run (not installed, offline on first use, no key), the campaign uses the next one (OpenAI → UniXcoder → TF-IDF), says so in the log and on the results, and records it in the manifest. Set `embedding.fallback: none` in `spreadex.yaml` to stop instead. Vectors are cached per input, so a re-run embeds only new inputs.

### Advanced

:::options
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

:::problem "UniXcoder … would use TF-IDF instead"
cause: torch and transformers are not installed, or the model could not be downloaded on first use.
fix: Run `pip install 'spreadex[neural]'` in the environment that runs SpreadEx, connect once so the model is cached, then restart the Workbench. Or choose TF-IDF deliberately.
:::

:::problem The estimate is much longer than expected
cause: With **Number of tests** or **Entire corpus**, the estimate assumes every input may use its full timeout.
fix: Use a **Time limit**, or lower the timeout in step 4.
:::

:::advanced Reproducibility
With equal count, a fixed seed, pinned generator versions and (for the Rhino example) a pinned runtime, the same configuration gives the same inputs, the same Cluster Coverage, the same selection and the same priority order. With several parallel executions the *order in which inputs finish* can vary, because a slow input finishes later; the priority order itself does not change. Every run records what it used in its manifest; see [Results](#guide/results#what-a-run-records).
:::

:::advanced Replay or regenerate
**Replay** executes a campaign's recorded inputs again, in their recorded order, as a new campaign: nothing is generated, embedded or reordered, so a later change of algorithm or settings cannot alter it (`spreadex replay <id> --execute`, or **Replay** in Campaigns). **Regenerate** starts a new campaign from the same configuration: new inputs, a new diversity map, the configured ordering (`spreadex replay <id> --regenerate`, or **Regenerate**). Campaigns recorded before ordering variants existed show their ordering as *unknown*; they are never relabelled.
:::

:::advanced How clusters are formed
Inputs are embedded (UniXcoder by default; see Diversity map), clustered with Affinity Propagation (sklearn's default damping, as in the SpreadEx study; if that does not converge, once more with damping 0.9, which the run reports and records), and each generator is scored by the share of clusters its inputs fall into. The order follows Algorithm 1 of the SpreadEx paper as published: the smallest cluster first (the most isolated one if several are equally small), then each cluster farthest from those already chosen; within a cluster, inputs farthest from its exemplar (the input closest to the cluster centroid) first; one input per cluster per round. `prioritization: {variant: replication}` instead uses the ordering of the paper's replication code, which produced its published results (Affinity Propagation's exemplar, closest inputs first). The clustering's effective number of clusters (*k_eff*) and any caveats (for example a clustering that did not converge) are reported with the scores.
:::
