import io.karatelabs.js.Engine;

import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * A test harness around Karate's JavaScript engine.
 *
 * Karate ships io.karatelabs.js.JsLauncher, which catches the exception,
 * prints a stack trace and then exits 0 anyway. For a campaign that is
 * useless: a script the engine refused is indistinguishable from one it ran,
 * so every input would be reported as a pass and the run would look perfect
 * while telling you nothing.
 *
 * This harness does what the ICST 2026 study's NashornRunner does -- report
 * the refusal on stderr in one line, and exit non-zero so the exit code means
 * something:
 *
 *     exit 0  the script ran
 *     exit 2  the engine refused it or it threw   -> expected_rejection
 *     exit 1  the harness itself could not run    -> a real problem
 *
 * An engine defect still escapes as a Java stack trace on an unexpected
 * throwable, which the campaign's crash_patterns catch.
 */
public class KarateRunner {

    public static void main(String[] args) {
        if (args.length != 1) {
            System.err.println("Usage: java KarateRunner <script.js>");
            System.exit(1);
        }

        String script;
        try {
            script = new String(Files.readAllBytes(Paths.get(args[0])));
        } catch (Exception e) {
            System.err.println("Harness error: cannot read " + args[0] + ": " + e);
            System.exit(1);
            return;
        }

        try {
            Object result = new Engine().eval(script);
            if (result != null) {
                System.out.println(result);
            }
        } catch (StackOverflowError | OutOfMemoryError fatal) {
            // Not the script's fault in any useful sense: let it print as the
            // engine-level failure it is.
            throw fatal;
        } catch (Exception e) {
            // One line, machine-readable, and the exit code agrees with it.
            System.err.println("JS ERROR: " + e.getClass().getSimpleName()
                               + ": " + e.getMessage());
            System.exit(2);
        }
    }
}
