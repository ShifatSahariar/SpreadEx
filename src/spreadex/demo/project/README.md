# The SpreadEx demo

A real campaign, start to finish, in a directory you can delete afterwards.

`calc.py` is an expression evaluator of about a hundred lines. It is the
system under test. Read it -- that is the point of it being this small.

It does three things, and a campaign tells them apart:

| Input | What calc.py does | What SpreadEx calls it |
|---|---|---|
| `1 + 2 * 3` | prints `7.0`, exits 0 | `ok` |
| `1 +`, `1 / 0` | `calc: SyntaxError: ...`, exits 1 | `expected_rejection` |
| `1 % 0` | ZeroDivisionError, uncaught | `crash` |

That middle row is the one that matters. Most of what a generator produces is
invalid, and a parser refusing it is the parser working. A tool that counted
those as failures would hand you thousands of findings and no information.
`spreadex.yaml` says how calc.py reports a rejection, and the oracle does the
rest.

The last row is a genuine defect, documented rather than hidden. `term()`
guards division by zero and the guard was never extended to the remainder
operator beside it, so `1 / 0` is reported cleanly and `1 % 0` crashes. An
incomplete guard covering one operator and not its sibling is one of the most
common bugs there is.

A campaign reports this one bug under **several** signatures (three with the
shipped configuration), because it crashes through different paths in the
parser. That is not a flaw in the run; it is why SpreadEx counts signatures and
never claims a bug count.

Whether a given campaign reaches it still depends on what the generators
produce under the budget. **If a run finds nothing, SpreadEx says so** -- a
demo that always finds a bug would be a marketing animation, not a test.

## Run it again

```
spreadex run
spreadex results
```

Then change something: raise the budget, add a generator, edit `calc.bnf`.
Fix the bug in `term()` and run again to watch the signature disappear. The
campaign is exactly what is in `spreadex.yaml`, and nothing else.
