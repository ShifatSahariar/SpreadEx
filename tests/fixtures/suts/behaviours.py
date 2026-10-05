#!/usr/bin/env python3
"""A system under test that produces each behaviour the pipeline must classify.

Deterministic by content: the verdict is decided by a keyword in the input, so
a test can assert exactly which classification the oracle should reach instead
of hoping a fuzzer stumbles into one. Every behaviour here is one a real SUT
exhibits, and each is a case the oracle has to tell apart:

  PASS        exit 0, nothing on stderr          -> ok
  REJECT      exit 1, a diagnostic it owns       -> expected_rejection
  CRASH       exit 3, a stack trace              -> crash
  HANG        never returns                      -> timeout
  QUIETCRASH  exit 0, but a stack trace          -> crash, and ONLY via
              on stderr                             crash_patterns: the exit
                                                    code says it passed

The last one is the reason crash_patterns are checked before anything else.
A SUT that catches its own fatal error and exits 0 anyway is common (Karate's
launcher and JavaBASIC both do it), and nothing but output inspection finds it.
"""

from __future__ import annotations

import sys
import time


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        text = open(argv[1], encoding="utf-8", errors="replace").read()
    else:
        text = sys.stdin.read()      # the stdin execution model

    if "HANG" in text:
        time.sleep(3600)
        return 0
    if "QUIETCRASH" in text:
        print("Caught an Exception :", file=sys.stderr)
        print("java.lang.ArrayIndexOutOfBoundsException: Index 256", file=sys.stderr)
        print("\tat fixture.Tokenizer.reset(Tokenizer.java:84)", file=sys.stderr)
        return 0                     # exits CLEAN despite having died
    if "CRASH" in text:
        print("Exception in thread \"main\" java.lang.NullPointerException",
              file=sys.stderr)
        print("\tat fixture.Parser.parse(Parser.java:12)", file=sys.stderr)
        return 3
    if "REJECT" in text:
        print(f"fixture: SyntaxError: cannot parse {text.strip()[:40]!r}",
              file=sys.stderr)
        return 1
    print(f"ok {len(text.strip())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
