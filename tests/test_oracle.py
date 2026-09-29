"""The oracle is the highest-stakes component: if it mistakes a correct
rejection for a crash, every run drowns in false positives."""

import pytest

from spreadex.exec.observation import Observation
from spreadex.exec.oracle import CrashOracle, DifferentialOracle, Verdict, make_oracle


def obs(sut="a", rc=0, sig=None, timed_out=False, out="", err="", version="1"):
    return Observation(
        input_hash="h", sut_id=sut, sut_version=version, exit_code=rc, signal=sig,
        timed_out=timed_out, duration_ms=1.0, stdout_hash="x", stderr_hash="y",
        stdout_preview=out, stderr_preview=err,
    )


class TestCrashOracle:
    def test_clean_exit_is_ok(self):
        assert CrashOracle().judge([obs(rc=0)]).verdict is Verdict.OK

    @pytest.mark.parametrize("err", [
        "SyntaxError: unexpected token at 1:0",
        "ParseError: bad input",
        "line 3:7 mismatched input 'x' expecting ID",
        "org.antlr.v4.runtime.RecognitionException",
        "no viable alternative at input '?'",
    ])
    def test_parse_refusal_is_not_a_crash(self, err):
        # The single most important behaviour in the tool.
        assert CrashOracle().judge([obs(rc=1, err=err)]).verdict is Verdict.EXPECTED_REJECTION

    def test_unexplained_nonzero_exit_is_a_crash(self):
        j = CrashOracle().judge([obs(rc=1, err="RuntimeError: internal compiler error")])
        assert j.verdict is Verdict.CRASH and j.signature

    def test_signal_is_always_a_crash(self):
        assert CrashOracle().judge([obs(rc=-11, sig=11)]).verdict is Verdict.CRASH

    def test_signal_beats_a_rejection_message(self):
        # A SUT that printed a syntax error and then died is still a crash.
        j = CrashOracle().judge([obs(rc=-6, sig=6, err="SyntaxError: nope")])
        assert j.verdict is Verdict.CRASH

    def test_timeout(self):
        assert CrashOracle().judge([obs(timed_out=True)]).verdict is Verdict.TIMEOUT

    def test_expected_exit_codes_are_configurable(self):
        o = CrashOracle(expected_exit_codes=(0, 1))
        assert o.judge([obs(rc=1, err="whatever")]).verdict is Verdict.OK

    def test_distinct_failures_get_distinct_signatures(self):
        a = CrashOracle().judge([obs(rc=1, err="RuntimeError: boom\n  at com.x.A.f(A.java:1)")])
        b = CrashOracle().judge([obs(rc=1, err="IllegalStateException: bad\n  at com.x.B.g(B.java:2)")])
        assert a.signature != b.signature

    def test_signature_survives_recompilation(self):
        # Line numbers and addresses must not enter the signature, or every
        # rebuild invents "new" bugs.
        a = CrashOracle().judge([obs(rc=1, err="RuntimeError: x\n\tat com.x.A.f(A.java:11)")])
        b = CrashOracle().judge([obs(rc=1, err="RuntimeError: x\n\tat com.x.A.f(A.java:99)")])
        assert a.signature == b.signature


class TestDifferentialOracle:
    def make(self):
        return DifferentialOracle(banners=("EngineA 1.0", "EngineB 2.0"))

    def test_agreement(self):
        o = self.make()
        v = o.judge([obs("a", out="EngineA 1.0\n42"), obs("b", out="EngineB 2.0\n42")])
        assert v.verdict is Verdict.OK

    def test_output_divergence(self):
        o = self.make()
        v = o.judge([obs("a", out="EngineA 1.0\n42"), obs("b", out="EngineB 2.0\n43")])
        assert v.verdict is Verdict.DIVERGENCE

    def test_acceptance_divergence(self):
        o = self.make()
        v = o.judge([obs("a", rc=0, out="ok"), obs("b", rc=1, err="ParseError: no")])
        assert v.verdict is Verdict.DIVERGENCE

    def test_both_reject_with_different_wording_is_agreement(self):
        # Engines word syntax errors differently. Treating that as a divergence
        # would flag every invalid input in the corpus.
        o = self.make()
        v = o.judge([obs("a", rc=1, err="SyntaxError: expected let"),
                     obs("b", rc=2, err="ParseError: unexpected token")])
        assert v.verdict is Verdict.EXPECTED_REJECTION

    def test_a_crash_outranks_a_divergence(self):
        o = self.make()
        v = o.judge([obs("a", rc=-11, sig=11), obs("b", rc=0, out="fine")])
        assert v.verdict is Verdict.CRASH

    def test_banners_are_stripped_before_comparing(self):
        o = self.make()
        v = o.judge([obs("a", out="EngineA 1.0\nsame"), obs("b", out="EngineB 2.0\nsame")])
        assert v.verdict is Verdict.OK

    def test_single_observation_falls_back_to_crash_oracle(self):
        assert self.make().judge([obs(rc=0)]).verdict is Verdict.OK


def test_make_oracle_rejects_unknown_type():
    with pytest.raises(ValueError):
        make_oracle({"type": "telepathy"})


def test_failure_verdicts_are_flagged_as_failures():
    assert Verdict.CRASH.is_failure and Verdict.TIMEOUT.is_failure and Verdict.DIVERGENCE.is_failure
    assert not Verdict.OK.is_failure and not Verdict.EXPECTED_REJECTION.is_failure
