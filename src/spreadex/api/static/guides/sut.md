# System under test

## What this step does

Step 1 tells SpreadEx **which program to test and how to run it on one input**. SpreadEx runs that command once for every generated input, so it has to be right before anything else is worth doing. **Test connection** runs it once, here, on a small sample, and shows what happened.

{{img:sut-start}}

## Your options

### Starting point

:::options
- **Start from an example**: opens a ready project (system, grammars and generators) as a *separate* project with its own Workbench. The project you are in is not changed. Two examples are available: **Rhino** (a real JavaScript engine) and **MiniCalc** (the guided tutorial).
- **Configure my own program**: the cards and command box below, for your own system under test.
:::

{{img:sut-examples}}

### How do you run your program?

These cards describe **how** a program is started. They do not choose *which* program is tested: picking **Java / JVM** does not mean Rhino. A card only changes the grey placeholder and the example on the right; it never overwrites a command you typed or one saved in `spreadex.yaml`.

:::options
- **Executable**: a command-line program that takes an input file, for example `./your-parser {input}`.
- **Java / JVM**: a JAR or Java class run with your JDK, for example `java -jar your-tool.jar {input}`.
- **Script / Runtime**: Python, Node.js, Ruby or another interpreter, for example `python3 your_parser.py {input}`.
- **Custom command**: any complete command you write yourself.
:::

### Execution command

The command SpreadEx runs for every input. `{input}` is replaced by the path of each generated test file; if it is missing, the path is appended at the end. Quote any argument that contains a space. Relative paths are read from the **project folder**.

### Test connection

Runs the command once on a sample input. The result is one of:

:::options
- **System ready!**: the program ran. A non-zero exit code here is often correct (a parser refusing the sample); what counts as a failure is decided in step 4.
- **It did not run**: the program could not be started at all, with the reason (for example a missing script, named against the project folder).
- **No answer in time**: it did not finish within the timeout. Either raise the timeout, or the program may be waiting on standard input.
:::

A successful test counts only for the **exact settings it ran with**: the command, working directory, environment, input mode, timeout and memory limit. Change any of them and the test has to be repeated. A test remembered from earlier in the same browser is shown as **Verified earlier in this browser**, never as a fresh result.

{{img:sut-ready}}

### Compare another implementation

Adds a second command for the same input language. With two or more implementations SpreadEx can do **differential testing** (step 4): it compares how they behave on the same input, so no expected output is needed.

### Advanced options

:::options
- **Working directory**: where the program runs. Empty means a clean scratch folder for every input.
- **Environment variables**: one `NAME=value` per line, added to the environment the program inherits.
- **Pass input via stdin**: for programs that read the input from standard input instead of a file path (for example an interactive interpreter).
- **Timeout per input**: how long one input may run, for example `5s` or `2m`.
- **Memory limit (MB)**: a per-input address-space limit. Linux enforces it; macOS often ignores it.
:::

## When to choose which

- Want to see SpreadEx working before configuring anything? **Start from an example**: MiniCalc for a guided tour, Rhino for a real engine.
- Testing your own program? **Configure my own program**, pick the card that matches how you start it, type the command, and **Test connection**.
- Your program reads from standard input and ignores file arguments? Turn on **Pass input via stdin**.
- You have two implementations of the same language? Add the second with **Compare another implementation**.

## Examples

:::tabs
::tab MiniCalc
The demo's calculator is a Python script:

```
python3 ./calc.py {input}
```

Open it from **Start from an example → MiniCalc**; the command is already filled in.
::tab Rhino
The Rhino example runs the public Rhino 1.9.1 release through its standard shell. `${SPREADEX_RUNTIME_RHINO}` is replaced by the pinned jar, which SpreadEx downloads once and verifies by SHA-256:

```
java -Xmx256m -Xss1m -XX:ReservedCodeCacheSize=32m -XX:CompressedClassSpaceSize=64m
     -XX:MaxMetaspaceSize=128m -XX:+UseSerialGC
     -cp ${SPREADEX_RUNTIME_RHINO} org.mozilla.javascript.tools.shell.Main {input}
```

The `-X` flags keep Java small enough to start under SpreadEx's per-input memory limit; without them a default JVM refuses to start on Linux.
::tab Your own program
A small JSON validator that exits 2 for invalid JSON, kept in your project folder:

```
python validate.py {input}
```

Choose **Script / Runtime**, type the command, press **Test connection**, then **Continue to Inputs**.
:::

## Common problems

:::problem It did not run: "validate.py is not in the project folder"
cause: The file named in the command does not exist where SpreadEx looks: relative paths are read from the project folder. Often a typo.
fix: Correct the file name, or give an absolute path, then press Test connection again.
:::

:::problem It did not run: "Java could not find the jar file" or "the main class"
cause: The jar path or class name in the command is wrong, or the jar is not in the project folder.
fix: Check the path after `-jar` or `-cp`. For the Rhino example run `spreadex runtimes install rhino`.
:::

:::problem It did not run: "Java could not start under the memory limit"
cause: The JVM reserves more address space than the per-input memory limit allows (Linux enforces this limit).
fix: Add JVM flags such as `-Xmx256m -XX:CompressedClassSpaceSize=64m`, or raise **Memory limit (MB)** under Advanced options.
:::

:::problem No answer in time
cause: The program is slow on the sample, or it is waiting for input on stdin.
fix: Raise **Timeout per input**, or turn on **Pass input via stdin** if the program reads its input that way.
:::

:::problem "Test the connection first" when pressing Continue
cause: The command or one of its options changed since the last successful test.
fix: Press **Test connection** again; Continue unlocks when it passes.
:::

:::advanced How SpreadEx runs each input
Every input runs in a fresh scratch folder (unless you set a working directory), so a misbehaving program cannot litter your project. Because of that, relative file paths in the command that exist in the project folder are rewritten to their full project path before running; a path that does not exist is reported against the project folder.

Standard input is closed in file mode, so a program that reads stdin by mistake ends instead of waiting forever.

A campaign whose program cannot start at all (a missing program, runtime or script, or a launcher error that also happens on an empty input) **fails** with a clear message instead of reporting every input as a crash. See [Troubleshooting](#guide/troubleshooting#campaign-setup-failures).
:::
