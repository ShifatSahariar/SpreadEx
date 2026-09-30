# Migration: research repository → SpreadEx

## The split

| | Research repository (`SpreadEx-2026`) | This repository (`spreadex`) |
|---|---|---|
| Purpose | the scientific record | the open-source product |
| Contents | experiments, SUTs, mutation, coverage, embeddings, statistics, replication data | the tool |
| Stability | frozen and reproducible | evolves |
| Role for algorithms | **specification / oracle** | tested production implementation |

**Nothing was moved destructively.** Every file was copied, and the research
repository remains runnable exactly as before. `git status` there shows no
deletions caused by this migration.

## What was extracted, and what proves it is faithful

The published algorithms live in `src/spreadex/prioritization/reference.py`.
Each function names the research function it mirrors. `tests/golden/` imports
the **real research code** — not a copy — and asserts agreement:

| Checked | Against |
|---|---|
| L2 normalization | `prioritization_utils.cluster_embeddings_once` |
| `K_eff` | `clustering_analysis_utils.perform_clustering` |
| Cluster Coverage values | `clustering_analysis_utils.cluster_coverage_pipeline` (driven through its own on-disk interface) |
| filename → generator attribution | `clustering_analysis_utils.load_all_vectors` |
| cluster ordering + tie-break | `by_centroid_spread.cluster_by_centroid_spread` |
| within-cluster ordering | `by_exemplar_distance.inputs_by_exemplar_distance` |
| final SpreadEx ordering (4 budget sequences) | `run_approaches_combo.create_round_robin_cluster_selector` |
| budget truncation is a prefix | the same |
| generator selection (incl. ties) | `tool_selection_ranksum.compute_ranksum_all_models` |

Run the gate:

```bash
pip install -e ".[golden]"
SPREADEX_REQUIRE_GOLDEN=1 pytest tests/golden -q
```

`SPREADEX_REQUIRE_GOLDEN=1` turns a skip into a failure, and
`SPREADEX_RESEARCH_REPO` is **authoritative** — if it points somewhere wrong the
gate fails rather than quietly finding another checkout and reporting a pass.

## Behaviours deliberately preserved

These are quirks of the published implementation. They are reproduced and
pinned by tests, so changing one becomes a visible decision rather than an
accident that silently invalidates the paper's results.

1. **Round-robin does at most one pass per call.** A `for ... else` breaks the
   outer loop whenever a full pass finishes without reaching the requested
   count, so a single request for more than *K* inputs returns at most one per
   cluster. The research driver compensates by requesting increments and
   tracking `last_budget_size`. `drive_budgets()` reproduces that loop, and the
   full ordering is defined as its limit.
2. **Cluster Coverage counts the `-1` noise label** as a touched cluster while
   excluding it from `K_eff`. Unobservable under Affinity Propagation (the
   published configuration), which labels nothing as noise.
3. **In-cluster ordering is closest-to-exemplar first.** The research call site
   passes no `direction`, so the function's `"closest"` default applies.
4. **RankSum ties take the best rank** (`method="min"`), and the winner is
   `idxmin`, which on a tie takes the first in index order.

## One divergence found during migration

`webapp/tool_mode/pipeline.py` in the research repository hardcodes
farthest-from-exemplar ordering, which contradicts the published
`SpreadEx_RR` configuration. **This repository implements the published
behaviour**, and `test_published_direction_is_closest_first` pins it. The
browser prototype in the research repository was not modified.

## One intentional extension

The failure-signature normalizers were written for JVM subject programs and
return `<no_exception>` for anything else, which would give every Python, JS or
native crash the same signature. This repository adds a generic fallback. The
comparison path that decides verdicts is unchanged and is asserted identical;
`test_generic_fallback_is_a_documented_extension` pins exactly where the two
differ.

## Not migrated

Experiments, SUT build configurations, mutation and coverage infrastructure,
embedding exports, and statistical analysis stay in the research repository.
They are the scientific record, not product code.


## What the golden pipeline taught us

Running the architecture against a real language runtime surfaced three things
that no synthetic example would have:

1. **Rhino exits 3 for a refused script and for an engine crash alike.** Exit
   codes cannot classify a language runtime's behaviour. `rejection_patterns`
   (the SUT's own diagnostics) and `crash_patterns` (checked first, so a broad
   rejection rule cannot mask a real bug) were added for this.
2. **Generated programs legitimately throw.** A program doing
   `throw new TypeError(...)` is Rhino working correctly. A narrower pattern
   list classified 15 such programs as crashes — a 100% false-positive rate on
   the failure count.
3. **`isla solve -n 150` returns 10 inputs.** Free instantiations default to 10
   and cap the expansion independently of `-n`. Both are now raised together,
   and the reason is recorded in the catalog entry.


## What the grammar adapter taught us

1. **A line-based grammar parser is not enough.** `"(" <e> ")"` uses parentheses
   as terminal text while `(", " <i>)*` uses them as grouping. The research
   prototype had to disable its own reachability check for Fandango grammars
   because of exactly this; a tokenizer that understands quoting does not need
   to.
2. **Inlining character classes balloons the grammar and breaks ISLa.**
   Expanding `r'[A-Za-z]{1,2}'` in place produced
   `"A" | ... | "z" | (A..z)(A..z)` and an 870-line grammar whose shape ISLa's
   parser rejected. Lifting each class into a shared rule gives 355 lines and a
   grammar ISLa accepts.
3. **Fandango rejects pipe-continuation lines.** Alternatives must be on one
   line or wrapped in parentheses; both leading-`|` and trailing-`|`
   continuations are syntax errors. This is not documented anywhere we found.
4. **Ambiguity cannot be treated as a hard blocker.** `rhino.fan` defines
   `IDENT_NUM` and `IDENT_STR` identically and ISLa fails on it;
   `rhino.bnf` has a duplicate pair too and ISLa handles it fine. So it is
   reported as a risk, not a refusal.
