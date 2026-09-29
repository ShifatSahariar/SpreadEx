# Example: differential testing (two implementations)

```bash
spreadex doctor
spreadex run
```

Expected: **45 passed, 10 rejected (expected), 5 divergences, 1 signature.**

The two engines reject malformed input with different wording and different
exit codes. Those are *agreements*, not divergences. The five real divergences
are the negative-number cases, where EngineB's arithmetic differs.
