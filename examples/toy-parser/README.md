# Example: toy parser (single target)

```bash
spreadex doctor
spreadex run
```

Expected: **40 passed, 15 rejected (expected), 5 crashes, 1 signature.**

The 15 malformed inputs are *correctly rejected* by the parser. A tool that
counted them as failures would report 20 "bugs" where there is one. Separating
those two cases is the job of the oracle.
