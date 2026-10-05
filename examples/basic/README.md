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

Any program line longer than 255 characters overflows it. Verified by hand:
252 characters is fine, 262 throws. The campaign reached it at input 3 of 160.

## The oracle is what made that visible

The first run of this example reported **126 crashes**. Exactly one of them
was the bug above; the other 125 were programs that jumped to a line number
they never defined, which JavaBASIC diagnoses perfectly well as
`Runtime Error: GOTO non-existent line 80`. That wording was missing from
`oracle.rejection_patterns`.

```
before: 127 crashes, 2 signatures   <- one real bug, buried
after:    3 crashes, 1 signature    <- the real bug, alone
```

One missing pattern was the difference between a usable report and a pile of
noise. It also cuts the other way: BASIC *catches* the overflow itself, prints
`Caught an Exception :` and still exits 0 — so neither the exit code nor the
rejection rules would have noticed it. `crash_patterns` are checked first for
exactly this reason.
