#!/usr/bin/env python3
"""Second implementation, with a planted semantic divergence on negatives.

It also words its rejection message differently and exits 2 rather than 1 --
on purpose. A differential oracle must treat "both refused this input" as
agreement, or every malformed input in the corpus is reported as a divergence.
"""
import sys

src = open(sys.argv[1]).read().strip()
print("EngineB 2.0 build 9")
t = src.split()
if not t or t[0] != "let":
    sys.stderr.write("ParseError: unexpected token\n")
    sys.exit(2)
nums = [int(x) for x in t if x.lstrip("-").isdigit()]
if any(v < 0 for v in nums):
    print("sum=", sum(abs(v) for v in nums))   # the planted bug
else:
    print("sum=", sum(nums))
