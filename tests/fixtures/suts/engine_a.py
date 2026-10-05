#!/usr/bin/env python3
"""One of two implementations, for differential testing.

Agrees with engine_b.py on everything except input containing DIVERGE, where
the two disagree about the answer, and ONLYA, which only this one accepts.
Both refuse REJECT, wording it differently -- engines do, and that must be
read as agreement rather than a divergence.
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    text = open(argv[1], encoding="utf-8", errors="replace").read() if len(argv) > 1 \
        else sys.stdin.read()
    if "REJECT" in text:
        print("engine-a: parse error near token 1", file=sys.stderr)
        return 1
    if "DIVERGE" in text:
        print("42")                 # b says 43
        return 0
    if "ONLYA" in text:
        print("accepted")           # b refuses this
        return 0
    print(f"ok {len(text.strip())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
