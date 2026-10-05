#!/usr/bin/env python3
"""The other of two implementations, for differential testing.

Agrees with engine_a.py on everything except input containing DIVERGE, where
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
        print("engine-b: parse error near token 1", file=sys.stderr)
        return 1
    if "DIVERGE" in text:
        print("43")                 # a says 42 -- a real output divergence
        return 0
    if "ONLYA" in text:
        # a accepts this; refusing it is an ACCEPTANCE divergence, which is
        # the more interesting of the two kinds.
        print("engine-b: unsupported construct", file=sys.stderr)
        return 1
    print(f"ok {len(text.strip())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
