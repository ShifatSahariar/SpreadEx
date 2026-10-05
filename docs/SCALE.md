# How far the diversity map goes

Affinity Propagation is O(n²) in time *and* memory, and the ICST 2026 results
were produced at roughly a thousand inputs. This is the measurement of what
happens above that, so the limit is a known number rather than something a
stranger discovers by taking their machine down.

Measured by `scripts/scale_audit.py` on 2026-10-05: macOS 15.5, x86_64,
36 GB RAM, Python 3.11, TF-IDF embeddings, synthetic programs with the shape
of generated input.

| pooled inputs | time | peak RSS | clusters | converged |
|---:|---:|---:|---:|---|
| 500 | 0.4 s | 0.21 GB | 53 | yes |
| 1,000 | 0.3 s | 0.34 GB | 106 | yes |
| 2,000 | 1.5 s | 0.71 GB | 248 | yes |
| 5,000 | 11.0 s | 2.5 GB | 590 | yes |
| 10,000 | 59.4 s | 6.3 GB | 1,012 | yes |

Memory grows as n² almost exactly. Time grows faster — roughly n^2.3, because
the iteration count climbs too. Extrapolating:

| pooled inputs | memory needed |
|---:|---:|
| 15,000 | ~14 GB |
| 20,000 | ~25 GB |
| 30,000 | ~55 GB |
| 50,000 | ~154 GB |

## What this means in practice

**Comfortable: up to ~5,000 pooled inputs.** Seconds, a couple of gigabytes,
fine on any laptop.

**Workable with room to spare: up to ~10,000.** A minute and 6 GB. Fine on a
16 GB machine, not on an 8 GB one.

**The wall is near 15,000–20,000 on ordinary hardware.** Affinity Propagation
does not degrade when it runs out of memory, it fails — and a campaign that
fails there has already paid for every input it generated.

So SpreadEx checks before it allocates. `signals/base.py` estimates the
requirement from the corpus size, warns past a quarter of the machine's
memory, and refuses past 70% with the lever named:

```
Clustering 50,000 inputs needs roughly 163.0 GB, and this machine has 8 GB.
  Affinity Propagation is O(n^2) in memory; it does not degrade, it fails.
  Fix: cap the pool with `budget: {max_inputs: 5000}`, lower `generation.cap`
       or `generation.per_generator`, or use `selection_signal: random`.
```

This is also why `generation.cap` defaults to 5,000 per generator under
`mode: time`. Grammarinator produced 20,000 JavaScript programs in 11.7
seconds on this machine; without a ceiling, one fast generator pools enough
input to make the clustering impossible.

## What this does not say

It does not say the approach scales. It says where it stops, which is the
cheaper thing to know. Getting past this needs a different clustering above
some threshold — MiniBatchKMeans or an HNSW-backed approach — with a
documented agreement check against exact AP in the range where both run. That
is real work and it is not done.

It also does not say 10,000 is enough. Whether a campaign needs more depends
on the budget it is given, and the equal-time runs in
[SUBJECTS.md](SUBJECTS.md) reach 20,000 in twenty seconds of generation. The
honest summary is that **the diversity map, not the generators, is currently
the limit on campaign size.**

## Reproducing

```bash
python scripts/scale_audit.py --sizes 500,1000,2000,5000,10000
```

Writes `docs/scale-audit.json`. Stop-on-timeout is built in, so pushing the
sizes higher on a bigger machine is safe.
