# JavaBASIC — and a real bug

This is the example that needs **`input_mode: stdin`**, and the one where a
campaign found an actual defect.

## Not distributed with SpreadEx

JavaBASIC (Chuck McManis, 1996) carries a **NON-COMMERCIAL-only** permission
notice in its source headers and ships no LICENSE file. We cannot bundle it or
fetch it for you. Compile your own copy, then:

```bash
export BASIC_CLASSES=/path/to/dir/containing/basic/*.class
spreadex run
```

## Why `input_mode: stdin`

JavaBASIC is a REPL. It reads the program from standard input and ignores
arguments entirely. Under the default `input_mode: file` SpreadEx would append
a path the interpreter never looks at, then wait while it sat at its prompt
expecting input that never arrived — **every single input recorded as a
timeout**.

`stdin` pipes the bytes in and then closes the stream. The closing matters as
much as the bytes: without EOF the interpreter waits for more.

## The bug

```
java.lang.ArrayIndexOutOfBoundsException: Index 256 out of bounds for length 256
	at basic.LexicalTokenizer.reset(LexicalTokenizer.java:84)
	at basic.CommandInterpreter.start(CommandInterpreter.java:210)
```

`LexicalTokenizer.reset()` copies a source line into a fixed 256-character
buffer with no bounds check:

```java
void reset(String x) {
    int l = x.length();
    for (int i = 0; i < l; i++) buffer[i] = x.charAt(i);
    buffer[l] = '\n';   // and this one is off the end when l == 256
    currentPos = 0;
}
```

Any program line of 256 characters or more overflows it. Verified by hand:
255 characters is fine, 256 throws (2026-10-16).

## The oracle is what made that visible

Measured on 2026-10-16 (SpreadEx 791839a, 4 generators x 150 inputs, all 600
executed; the four campaigns generated identical inputs):

| Oracle | Crashes reported | Signatures |
|---|---|---|
| as shipped in this folder | 10 | 1 (all the overflow) |
| without `rejection_patterns` | 474 | 2 (464 correctly rejected programs + the 10) |
| without `crash_patterns` | 0 | 0 (the overflow is reported as ok) |

Without the rejection rules the real defect is buried under programs JavaBASIC
diagnoses perfectly well (for example `Runtime Error: GOTO non-existent line`).
And it cuts the other way: BASIC *catches* the overflow itself, prints
`Caught an Exception :` and still exits 0, so neither the exit code nor the
rejection rules would notice it. `crash_patterns` are checked first for exactly
this reason.
