#!/usr/bin/env python3
"""A deliberately small SUT, with one planted bug.

Three behaviours SpreadEx must tell apart:
  valid input      -> exit 0                      (ok)
  malformed input  -> exit 1 + "SyntaxError: ..." (expected_rejection, NOT a bug)
  'deep' input     -> uncaught RecursionError     (crash -- the planted bug)
"""
import sys

src = open(sys.argv[1]).read().strip()
tokens = src.split()
if not tokens or tokens[0] != "let":
    sys.stderr.write("SyntaxError: expected 'let' at line 1:0\n")
    sys.exit(1)
if "deep" in src:
    raise RecursionError("maximum recursion depth exceeded in evaluator")
print("ok:", len(tokens), "tokens")
