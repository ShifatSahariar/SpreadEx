"""How far does the diversity map actually go?

Affinity Propagation is O(n^2) in both time and memory, and the ICST 2026
results were produced at roughly a thousand inputs. Real campaigns are larger
-- this project's own equal-time Rhino run pooled 21,000 -- so the question
is not academic: it decides whether SpreadEx is a tool or a demo.

This measures, it does not fix. The output tells us where to put a warning or
a fallback, which is a cheaper thing to know than to guess.

    python scripts/scale_audit.py --sizes 500,1000,2000,5000,10000
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from spreadex.signals.base import ClusterCoverageSignal, Item  # noqa: E402

WORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
         "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi"]
OPS = ["+", "-", "*", "/", "%", "&&", "||", "<", ">", "=="]


def synthetic_corpus(n: int, generators: int = 4, seed: int = 42) -> list[Item]:
    """Programs with the shape of generated input: repetitive, structured, and
    drawn from a small vocabulary -- which is the hard case for clustering,
    not the easy one."""
    rng = np.random.default_rng(seed)
    items = []
    for i in range(n):
        depth = int(rng.integers(1, 5))
        parts = []
        for _ in range(depth):
            parts.append(f"var {rng.choice(WORDS)} = "
                         f"{rng.integers(0, 999)} {rng.choice(OPS)} "
                         f"{rng.choice(WORDS)};")
        items.append(Item(blob_hash=f"h{i:06d}", text="\n".join(parts),
                          generator=f"gen{i % generators}"))
    return items


def peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes.
    return usage / (1024 * 1024) if sys.platform == "darwin" else usage / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="500,1000,2000,5000,10000")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="stop climbing once one size takes longer than this")
    ap.add_argument("--out", default="docs/scale-audit.json")
    args = ap.parse_args()

    rows = []
    for size in [int(s) for s in args.sizes.split(",")]:
        items = synthetic_corpus(size)
        before = peak_rss_mb()
        start = time.perf_counter()
        try:
            ordering = ClusterCoverageSignal(embedding_model="tfidf",
                                             random_state=42).rank(items)
        except MemoryError:
            rows.append({"n": size, "status": "MemoryError"})
            print(f"  n={size:>6}  MemoryError")
            break
        elapsed = time.perf_counter() - start
        peak = peak_rss_mb()
        row = {
            "n": size,
            "status": "ok",
            "seconds": round(elapsed, 2),
            "peak_rss_mb": round(peak, 1),
            "rss_growth_mb": round(peak - before, 1),
            "k_eff": ordering.k_eff,
            "converged": not ordering.caveats,
            "caveats": ordering.caveats,
        }
        rows.append(row)
        print(f"  n={size:>6}  {elapsed:>7.1f}s  peak {peak:>7.1f} MB  "
              f"k_eff={ordering.k_eff:<5} "
              f"{'converged' if row['converged'] else 'DID NOT CONVERGE'}")
        if elapsed > args.timeout:
            print(f"  stopping: {size} took longer than the {args.timeout:.0f}s limit")
            break

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "_what": "Runtime and peak memory of the CC diversity map (TF-IDF +"
                 " Affinity Propagation) against corpus size.",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "rows": rows,
    }, indent=2) + "\n")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
