#!/usr/bin/env python3
"""Reference implementation. Sums the integers in a `let` statement."""
import sys

src = open(sys.argv[1]).read().strip()
print("EngineA 1.0")
t = src.split()
if not t or t[0] != "let":
    sys.stderr.write("SyntaxError: expected 'let'\n")
    sys.exit(1)
print("sum=", sum(int(x) for x in t if x.lstrip("-").isdigit()))
