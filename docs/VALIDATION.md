# Pipeline validation matrix

What this answers: does an input that enters one end of SpreadEx come out of
the other correctly classified, persisted, reportable, replayable and
exportable? Not whether the algorithms are the published ones — that is
`tests/golden/` and `tests/test_golden_fixtures.py`.

## The four campaigns

| | shape | execution | oracle | generation |
|---|---|---|---|---|
| **A** | the owned demo SUT (`calc.py`) | file | crash | **real**, FuzzingBook |
| **B** | behaviour fixture, every verdict | file | crash | seed corpus |
| **C** | the same SUT over **stdin** | stdin | crash | seed corpus |
| **D** | two implementations that disagree | file | **differential** | seed corpus |

`tests/test_pipeline_matrix.py`

## The deliberate fixtures

`tests/fixtures/suts/behaviours.py` decides its behaviour from a keyword in
the input, so a test asserts exactly which classification the oracle *should*
reach rather than hoping a generator stumbles into one.

| fixture | what the SUT does | required verdict |
|---|---|---|
| `pass_plain`, `pass_other` | exit 0, clean | `ok` |
| `reject_syntax` | exit 1 + its own diagnostic | `expected_rejection` |
| `crash_npe` | exit 3 + stack trace | `crash` |
| `crash_quiet` | **exit 0** + stack trace | `crash` |
| `hang_forever` | never returns | `timeout` |
| `diverge_output` | engines print 42 vs 43 | `divergence` |
| `diverge_acceptance` | one accepts, one refuses | `divergence` |
| `agree_reject` | both refuse, worded differently | `expected_rejection` |

`crash_quiet` is the one worth naming: it exits cleanly and is only visible
through `crash_patterns`, which is why they are checked before the exit code
is believed. Karate's launcher and JavaBASIC both behave this way in reality.

## Invariants asserted at each seam

**Counts** — `generated ≥ valid ≥ prioritized ≥ executed`, nothing invented at
any stage, and every executed input classified exactly once into a known
verdict.

**Prioritization is a permutation, not a filter** — the prioritized stream is
the whole unique valid corpus, checked against the database rather than
against itself.

**Corpus** — every execution names a blob the store can resolve, and every
stored blob's SHA-256 matches its content.

**Differential** — one verdict per input, replicated across both target rows,
with each target's own exit code preserved; `executed` counts inputs, not
target invocations, so a two-target campaign does not look twice as
productive as it is.

**Execution model** — stdin and file execution must produce *identical*
verdict distributions, and stdin mode must pass no path argument.

**CC and selection** — scores bounded in [0,1], every scored generator
counted and vice versa, and the published RankSum selection agrees with the
highest CC on this campaign's own numbers.

**Results, replay, export** — `results.jsonl` agrees with the database row for
row; the manifest records the executed count, verdicts and config hash; a
reload of an unchanged project hashes the same; replay does not mutate the
run; the export carries `spreadex.yaml`, the manifest, the results and the
actual failing inputs.

**Interfaces** (`tests/test_pipeline_interfaces.py`) — a config written through
the UI's own save path loads to the same normalized object the CLI loads, by
hash; a config the CLI could not load is refused and never written; the UI's
API and the CLI's store report the same runs, verdicts, config hash and
failure signatures.

**Generator isolation** — each generator has its own environment directory and
interpreter, and none shares a `sys.prefix` with the tool. Deliberately *not*
a comparison of resolved interpreter paths: every venv symlinks back to the
same base interpreter, so that check passes while proving nothing.

**Partial failure** — one broken generator does not abort a campaign that has
other sources, and the failure is reported rather than swallowed. A campaign
with *no* usable source fails loudly instead of reporting an empty success.

## Clean-wheel acceptance

`tests/test_clean_wheel_acceptance.py` (marked `network`) builds the wheel,
installs it into an empty virtualenv, and runs the journey from a scratch
directory outside both repositories — then asserts that neither the resolved
package path nor anything recorded in the manifest points back into
`Documents/RESEARCH/{spreadex,SpreadEx-2026,ClusGram}`, and that the install
is not an editable one wearing a wheel's clothes.

It covers both halves of the v0.1 criterion: `spreadex demo` producing a real
campaign, and a stranger configuring a SUT the tool has never seen.

```bash
pytest tests/test_clean_wheel_acceptance.py -m network
```

## Does the matrix bite?

A validation suite that cannot fail is decoration. Each of these mutations was
applied to the product and the matrix caught it:

| mutation | result |
|---|---|
| `crash_patterns` no longer checked first | 2 failed |
| stdin mode appends a path argument | 1 failed |
| mutual rejection reported as divergence | 1 failed |
| prioritization silently drops inputs | 4 failed |

Re-check with the mutation loop in the project's own history, or by making the
change and running `pytest tests/test_pipeline_matrix.py`.
