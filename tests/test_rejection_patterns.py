"""Per-SUT rejection detection.

For a language runtime, a script-level error is the engine working correctly.
Rhino exits 3 both for a program it refused to parse and for an engine crash,
so the exit code cannot separate them and generic keywords are not reliable
either. `oracle.rejection_patterns` lets a SUT's own diagnostics do it.
"""

import pytest

from spreadex.exec.oracle import CrashOracle, Verdict, make_oracle
from spreadex.exec.signature import looks_like_rejection
from tests.test_oracle import obs

RHINO_PATTERNS = [
    r"^js: .*: Compilation produced [0-9]+ syntax error",
    r"^js: .*: uncaught JavaScript runtime exception",
    r"^js: .*: missing ",
]

RHINO_SYNTAX_ERROR = (
    'js: "/tmp/x.js", line 1: missing variable name\n'
    "js: var = = !!!\n"
    "js: .....^\n"
    'js: "/tmp/x.js", line 1: Compilation produced 1 syntax errors.\n'
)
RHINO_RUNTIME_ERROR = (
    'js: "/tmp/x.js", line 1: uncaught JavaScript runtime exception: '
    'TypeError: Cannot call method "foo" of null\n\tat /tmp/x.js:1\n'
)
RHINO_ENGINE_CRASH = (
    'Exception in thread "main" java.lang.StackOverflowError\n'
    "\tat org.mozilla.javascript.Parser.statement(Parser.java:1234)\n"
)


def test_generic_markers_now_catch_spaced_syntax_error():
    """Rhino writes "syntax errors", not "SyntaxError". The built-in list missed
    it, which made every invalid program look like a crash."""
    assert looks_like_rejection("Compilation produced 1 syntax errors.")


@pytest.mark.parametrize("stderr", [RHINO_SYNTAX_ERROR, RHINO_RUNTIME_ERROR])
def test_rhino_script_errors_are_rejections(stderr):
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=RHINO_PATTERNS)
    assert o.judge([obs(rc=3, err=stderr)]).verdict is Verdict.EXPECTED_REJECTION


def test_rhino_engine_crash_is_still_a_crash():
    """The whole point: the same exit code, but a real bug must survive."""
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=RHINO_PATTERNS)
    j = o.judge([obs(rc=3, err=RHINO_ENGINE_CRASH)])
    assert j.verdict is Verdict.CRASH
    assert j.signature


def test_patterns_replace_rather_than_extend_the_defaults():
    """An explicit pattern list is authoritative, so a SUT whose output happens
    to contain a generic keyword is not misread as rejecting."""
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=[r"^NOPE$"])
    assert o.judge([obs(rc=1, err="SyntaxError: boom")]).verdict is Verdict.CRASH


def test_patterns_are_case_insensitive_and_multiline():
    assert looks_like_rejection("first line\nJS: x: MISSING variable", patterns=[r"^js: .*: missing "])


def test_make_oracle_threads_patterns_through():
    o = make_oracle({"type": "crash", "rejection_patterns": RHINO_PATTERNS})
    assert o.judge([obs(rc=3, err=RHINO_SYNTAX_ERROR)]).verdict is Verdict.EXPECTED_REJECTION
    d = make_oracle({"type": "differential", "rejection_patterns": RHINO_PATTERNS})
    assert d._single.rejection_patterns == RHINO_PATTERNS


RHINO_EXPLICIT_THROW = (
    'js: "/tmp/x.js", line 4: exception from uncaught JavaScript throw: TypeError: TU6Cd\n'
    "\tat /tmp/x.js:4\n"
)
RHINO_BROAD = [r"^js: "]
RHINO_CRASH = [r"^Exception in thread", r"^\s*at org\.mozilla\.javascript\.", r"StackOverflowError"]


def test_explicit_javascript_throw_is_not_an_engine_bug():
    """Regression from the Rhino pipeline: a generated program that does
    `throw new TypeError(...)` is Rhino behaving correctly. A narrower pattern
    list reported 15 such programs as crashes."""
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=RHINO_BROAD,
                    crash_patterns=RHINO_CRASH)
    assert o.judge([obs(rc=3, err=RHINO_EXPLICIT_THROW)]).verdict is Verdict.EXPECTED_REJECTION


def test_crash_patterns_outrank_a_broad_rejection_rule():
    """`^js: ` is broad on purpose; crash_patterns keep it from hiding real bugs."""
    mixed = 'js: something\nException in thread "main" java.lang.StackOverflowError\n'
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=RHINO_BROAD,
                    crash_patterns=RHINO_CRASH)
    j = o.judge([obs(rc=3, err=mixed)])
    assert j.verdict is Verdict.CRASH and j.signature


def test_engine_stack_frame_alone_is_a_crash():
    err = 'js: oops\n\tat org.mozilla.javascript.Parser.statement(Parser.java:12)\n'
    o = CrashOracle(expected_exit_codes=(0,), rejection_patterns=RHINO_BROAD,
                    crash_patterns=RHINO_CRASH)
    assert o.judge([obs(rc=3, err=err)]).verdict is Verdict.CRASH


def test_make_oracle_threads_crash_patterns_through():
    o = make_oracle({"type": "crash", "rejection_patterns": RHINO_BROAD,
                     "crash_patterns": RHINO_CRASH})
    assert o.judge([obs(rc=3, err=RHINO_EXPLICIT_THROW)]).verdict is Verdict.EXPECTED_REJECTION
