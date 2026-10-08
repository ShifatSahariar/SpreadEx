# Results, findings and replay

## What this section covers

**Campaigns** lists every campaign of this project. Open one to see what ran, what failed, how the budget was spent and which generator reached the most of the input space, and to **replay** a finding to check that it still happens.

{{img:results-list}}

## Campaign statuses

:::options
- **Running**: in progress; open it to watch live.
- **Completed**: the campaign finished.
- **Cancelled**: stopped by you before the end; what ran is kept.
- **Interrupted**: stopped without finishing (for example the process was killed).
- **Failed**: the campaign could not test anything, for example because the system under test could not be started. See [Troubleshooting](#guide/troubleshooting#campaign-setup-failures).
:::

Each row offers **Re-run** (the same configuration again), **Export** (a zip with the run's manifest and results, the project's `spreadex.yaml`, and the input behind every failure) and delete. Deleting a campaign keeps inputs that another campaign still uses.

## Inside a campaign

:::options
- **Overview**: how many inputs ran and how each was classified, and how many distinct failures were found.
- **Generators**: per generator: inputs generated, valid, executed, failing inputs, pass rate and Cluster Coverage. Tags show **Selected by CC** / **Not selected** and **Replayed recording**.
- **Budget**: how failures were reached as inputs ran (the budget curve), so you can see whether prioritization reached them early.
- **Findings**: each distinct failure (grouped by signature), with the input, what the program printed, the classification evidence, and **Replay**.
- **Corpus**: every input of the campaign, with filters and search.
:::

{{img:results-generators}}

> [!WARN]
> When a generator's inputs were **replayed from a recording**, the Generators tab says so: those inputs were generated earlier and the others now, so the comparison is a demonstration, **not a controlled comparison** of the generators.

### Findings and their evidence

A finding is a **crash**, a **timeout** or a **divergence**. Expected rejections are never findings. For each finding SpreadEx shows the **evidence**: which rule classified it (timeout, signal, crash pattern, exit code, rejection rule), so you can check the classification rather than trust it.

{{img:results-findings}}

### Replay

**Replay** runs the finding's input again with the project's **current** command and testing strategy, and reports **Reproduced** or **Not reproduced**. Nothing is written: a replay is an observation, not a new campaign. A finding that no longer reproduces after you changed the program is a sign the fix worked.

> [!OK]
> Fixed a bug? Replay its finding: **Not reproduced** confirms the fix on that input. Then run a new campaign to look for others.

## Examples

:::tabs
::tab MiniCalc
The known defect, `1 % 0` crashing with a Python traceback, appears as a **crash** finding. Replay it after fixing `calc.py` and it reports **Not reproduced**.
::tab Rhino
The reference campaign executes Fandango's 100 programs: 53 pass, 46 are **expected rejections** (script errors Rhino reports with `js:`), and 1 is a **timeout**: a program that loops forever. That timeout is an input that never ends, not a confirmed defect in Rhino. The Generators tab marks Fuzz4All as **Replayed recording**.
::tab Your own program
For the JSON validator, a first run reports its refusals as crashes and suggests a rejection pattern; after adding `^invalid`, the same inputs appear as **expected rejections** and only real failures remain.
:::

## What a run records

Every campaign writes a manifest, so its results can be explained and checked later:

- the configuration and its hash, the seed, and SpreadEx's version;
- the command of every target and, for a pinned runtime such as Rhino, its version, download URL and SHA-256;
- each generator's grammar file and its checksum;
- for each generator, whether its inputs were **fresh** or **recorded**, how many were asked for and produced, and, for a recording, where it came from and its provenance;
- the Cluster Coverage scores and which generators were selected;
- the outcomes, the signatures and the budget curve;
- the platform, Python and Java versions.

It never records API keys or other secrets from your environment.

## Common problems

:::problem "Not reproduced" for a finding you have not fixed
cause: The failure depends on timing (a timeout near the limit, a busy machine) or on state outside the input.
fix: Replay again; for timeouts, compare the duration with the timeout. A flaky finding is worth knowing about, but treat it with care.
:::

:::problem Export failed
cause: The campaign is still running, or its files were removed.
fix: Wait until it finishes, or export another campaign.
:::

:::advanced Command-line equivalents
`spreadex results` summarises the last campaign (`--all` lists them). `spreadex replay <run>` shows what a past campaign used and whether the configuration has changed since (`--execute` runs it again). `spreadex export` writes the zip. `spreadex record <run> <generator> -o <folder>` saves one generator's inputs so they can be replayed without regenerating.
:::
