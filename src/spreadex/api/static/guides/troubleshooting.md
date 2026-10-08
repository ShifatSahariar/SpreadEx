# Troubleshooting and CLI reference

## Start with spreadex doctor

`spreadex doctor` checks the whole setup and prints a fix for every problem. It runs the system under test once, on a sample, so a broken command is caught before a campaign. Each line is ✓ (fine), ! (warning) or ✗ (problem, with **fix:**):

:::options
- **spreadex.yaml**: the configuration was found and parses.
- **java for &lt;runtime&gt;** and **runtime '&lt;name&gt;'**: for a pinned runtime such as Rhino, that Java is new enough and the runtime is downloaded and verified.
- **target 'sut'** and **target 'sut' runs**: the program exists, and actually starts on a sample input.
- **oracle**: which kind of testing strategy is configured.
- **corpus** / **input source**: there is something to generate inputs from or a folder of inputs.
- **generator '&lt;name&gt;'** and **grammar for '&lt;id&gt;'**: each generator is installed (or, for a replayed one, its recording verifies) and has a grammar in its format.
- **embedding**: the clustering model can be used.
- **corpus writable**: results can be saved in the project.
:::

## Campaign setup failures

> [!FAIL]
> **"The campaign failed: the system under test could not be started."** Nothing was tested. The campaign is shown as **Failed**, the command line exits with a non-zero status, and no findings are recorded.

It happens when the program cannot be started at all: the program or interpreter is not installed, a script or jar named in the command is missing, a pinned runtime is not installed, or the launcher reports that it could not start (for example Java under the memory limit).

To avoid false alarms, a launcher-style message on the first input only counts if the **same command also fails on an empty input**. A program that merely prints such a message for some input (a generated program printing "Cannot find module", say) is judged like any other output.

:::problem "… is not in the project folder"
cause: A file named in the command does not exist; relative paths are read from the project folder.
fix: Correct the path in step 1 (or in `spreadex.yaml`), then `spreadex doctor`.
:::

:::problem "command not found: 'java'" (campaign) / "'java' was not found" (Test connection)
cause: The program in the command is not installed or not on PATH.
fix: Install it, or give its full path. Java 11 or newer is needed for the Rhino example.
:::

:::problem "Rhino JavaScript engine 1.9.1 is not installed"
cause: The command refers to `${SPREADEX_RUNTIME_RHINO}` but the runtime has not been downloaded.
fix: `spreadex runtimes install rhino`. Opening the example from the Workbench does this for you.
:::

## Runtime downloads

:::problem "could not download Rhino …"
cause: No network, or the download was interrupted. Nothing partial is kept.
fix: Check the network and run `spreadex runtimes install rhino` again. After one successful download the runtime is reused offline.
:::

:::problem "does not match its pinned checksum … it was discarded"
cause: The downloaded file is not the pinned release byte for byte.
fix: Run the install again. If it persists, something on the network is changing the download; do not use it.
:::

> [!OK]
> `spreadex runtimes` lists the pinned runtimes and whether each is installed and verified.

## Configuration

:::problem All later steps are locked
cause: Steps unlock in order: each needs the previous one done. Free navigation between all five steps needs both a valid `spreadex.yaml` **and** at least one campaign in this project.
fix: Complete step 1 (Test connection, Continue), then each step in turn. Old campaigns stay listed under Campaigns either way.
:::

:::problem The Workbench shows the old settings after editing spreadex.yaml
cause: It re-reads the file on the next page load.
fix: Reload the page. A file that no longer parses is reported, and the project is treated as not configured until it is fixed; a campaign cannot start from it.
:::

:::problem "A campaign is already running"
cause: One campaign per project at a time, from any Workbench or the command line.
fix: Wait, open it from Campaigns, or `spreadex runs cancel`.
:::

## Generators

See [Generators](#guide/generators#common-problems) for install failures, altered recordings, and why live Fuzz4All is not available yet.

## Platforms

| Platform | Status |
|---|---|
| macOS (arm64) | Verified from a clean install: unit tests and every acceptance journey |
| Linux | Partly verified, in containers: the Rhino journey on arm64, the demo and custom-SUT journeys on x86_64. The unit suite has not yet passed on Linux (one clustering test depends on platform numerics). |
| Windows | **Unverified**: Windows-specific code exists (for example the campaign lock) and CI is configured, but it has not run there yet |

> [!WARN]
> On Linux arm64 some generators need a C compiler to install (for example FuzzingBook's `z3-solver` has no prebuilt package there).

## Not yet available

> [!NOTE]
> **Live Fuzz4All generation** and a **shared LLM configuration** for generators are not available in this version. Fuzz4All replays a recorded corpus. The experimental grammar assistant (`spreadex ui --experimental`) is a separate, opt-in feature for drafting grammars and constraints.

## Command-line reference

Generated from SpreadEx's own command parser, so it always matches the installed version. Run `spreadex <command> -h` for full details.

{{cli}}
