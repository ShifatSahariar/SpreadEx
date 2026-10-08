# Testing strategy

## What this step does

Step 4 decides **what counts as a failure**. Every input's run is classified into exactly one outcome; only some outcomes are findings. Getting this right is what separates a useful report from hundreds of false alarms.

{{img:strategy-checks}}

## The outcomes

| Outcome | Meaning | A finding? |
|---|---|---|
| **Passed** | The program ran and nothing was wrong. | no |
| **Expected rejection** | The program *correctly refused* the input, for example "syntax error". Most generated inputs are invalid, and refusing them is right. | no |
| **Crash** | The program failed: it was killed by a signal, printed a crash pattern, or exited non-zero without a known rejection message. | yes |
| **Timeout** | No answer within the timeout. A hang or a very slow input; **not proof of a bug**: an input can legitimately loop forever. | yes |
| **Divergence** | Two implementations disagreed on the same input (differential testing). | yes |

> [!FAIL]
> A **campaign setup failure** is different from all of these: the program could not be *started* (a missing program, runtime or script). Nothing was tested, the campaign is marked **Failed**, and no findings are recorded. See [Troubleshooting](#guide/troubleshooting#campaign-setup-failures).

## Your options

### Presets

**Use a preset** fills in the checks and patterns for a common kind of system; you can change everything afterwards.

:::options
- **Compiler / Parser**: crashes, timeouts and rejections, with typical rejection messages (`SyntaxError`, `ParseError`).
- **Interpreter**: crashes and timeouts, with typical crash messages (`Segmentation fault`, `Assertion failed`, `panic:`).
- **Custom**: start from scratch.
:::

### What to detect

:::options
- **Crashes & timeouts**: always on. A signal, a crash-shaped exit, or no answer before the timeout.
- **Expected rejections**: how your program says "I refuse this input". Give **Rejection message patterns** (regular expressions) and **Exit codes that are not failures**. Without them, every invalid input is reported as a crash.
- **Failure signatures**: **Crash / error message patterns** that always mean a real failure. They are checked *before* the rejection rules, so a broad rejection rule cannot hide a real bug.
- **Differential testing**: needs two or more implementations (step 1). A different exit class, exception or output is a divergence; no expected output is needed.
:::

**Execution timeout** sets how long one input may run before it counts as a timeout.

## When to choose which

- A parser or compiler that exits non-zero on bad input? **Compiler / Parser**, and give its rejection message.
- An interpreter where a bad program is normal and a crash is rare? **Interpreter**, with crash patterns.
- Two implementations of the same language? **Differential testing**.
- Not sure how your program refuses input? Use **See how your system refuses invalid input**, or run once: SpreadEx points out crashes whose messages look like rejections and suggests a pattern. It never applies the suggestion for you.

## Examples

:::tabs
::tab MiniCalc
Crashes and timeouts. MiniCalc's known defect (a remainder by zero) is a real crash with a Python traceback.
::tab Rhino
Rhino exits with code 3 both for a script it refused and for an engine crash, so exit codes cannot separate them. Messages can:

```
crash_patterns:        # checked first
  - "^Exception in thread"
  - "^\\s*at org\\.mozilla\\.javascript\\."
  - "StackOverflowError"
  - "OutOfMemoryError"
  - "AssertionError"
rejection_patterns:
  - "^js: "            # every script-level diagnostic
```

A generated `do { … } while (new ReferenceError())` loops forever and is reported as a **timeout**: an input that never ends, not a confirmed defect in Rhino.
::tab Your own program
The JSON validator prints `invalid: …` and exits 2 for bad JSON. After the first run SpreadEx notices that these "crashes" look like rejections and suggests `"^invalid"`. Add it as a rejection pattern; the next run reports them as **expected rejections**.
:::

## Common problems

:::problem Almost every input is a crash
cause: The program's normal way of refusing input is not described, so each refusal is counted as a failure.
fix: Add its message under **Rejection message patterns** (or its exit code under **Exit codes that are not failures**), then run again.
:::

:::problem A rejection rule might hide real bugs
cause: A very broad rejection pattern (for example `Error`) also matches crash output.
fix: Add the crash messages under **Crash / error message patterns**: they are checked first.
:::

:::problem Many timeouts
cause: The timeout is too short for the program, or the machine is busy (parallel executions).
fix: Raise **Execution timeout**, or lower parallel executions in Review & run.
:::

:::advanced The order of the rules
For each input the oracle decides, in this order: a **timeout**; a **signal** (always a crash); a **crash pattern** (crash); an **expected exit code** (passed); a **rejection pattern** (expected rejection); anything else non-zero is a **crash**. A crash pattern therefore outranks every rejection rule.
:::

:::advanced Signatures
Failures are grouped by a *signature* built from the failure's message and the innermost frames of its stack trace, with file paths removed so the same failure gives the same signature on another machine. A signature is not a bug: two bugs can share one, and one bug can produce several.
:::
