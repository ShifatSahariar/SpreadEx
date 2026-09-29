"""Oracles: turn Observations into a Verdict.

This is the boundary the rest of the tool depends on. An Observation is a
measurement; only an Oracle decides what it *means*. For parsers, compilers and
interpreters a non-zero exit code is usually correct behaviour -- the SUT was
handed a nonsense program and said so. Treating that as a failure would drown
the user in false positives on the first run.

The comparison logic in DifferentialOracle is lifted from
research/MUT_KILLING_PROFILE/Mutation_Killing_Profile.py::determine_mutant_status
(return code -> exception -> stdout), which is already a general two-run
divergence check.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol, Sequence

from .observation import Observation
from .signature import (
    failure_signature,
    looks_like_crash,
    filter_banners,
    looks_like_rejection,
    norm_text,
    normalize_exception_for_compare,
    extract_exception_normalized,
)


class Verdict(str, Enum):
    OK = "ok"                                # ran, nothing notable
    EXPECTED_REJECTION = "expected_rejection"  # SUT correctly refused the input
    CRASH = "crash"
    TIMEOUT = "timeout"
    DIVERGENCE = "divergence"                # targets disagreed

    @property
    def is_failure(self) -> bool:
        return self in (Verdict.CRASH, Verdict.TIMEOUT, Verdict.DIVERGENCE)


@dataclass(frozen=True)
class Judgement:
    verdict: Verdict
    signature: str | None = None
    detail: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.verdict.is_failure


class Oracle(Protocol):
    name: str

    def judge(self, observations: Sequence[Observation]) -> Judgement: ...


class CrashOracle:
    """Single-target oracle: crash, timeout, or a legitimate rejection."""

    name = "crash"

    def __init__(
        self,
        expected_exit_codes: Iterable[int] = (0,),
        rejection_patterns: Sequence[str] | None = None,
        crash_patterns: Sequence[str] | None = None,
    ) -> None:
        # Many CLIs exit 1 on invalid input by design; let the user say so.
        self.expected_exit_codes = set(expected_exit_codes)
        # Regexes identifying this SUT's own "I refused that input" messages.
        self.rejection_patterns = list(rejection_patterns or [])
        # Regexes that mean a genuine failure, checked FIRST so that a broad
        # rejection pattern cannot hide a real bug.
        self.crash_patterns = list(crash_patterns or [])

    def judge(self, observations: Sequence[Observation]) -> Judgement:
        if not observations:
            return Judgement(Verdict.OK)
        obs = observations[0]

        if obs.timed_out:
            return Judgement(Verdict.TIMEOUT, signature="timeout", detail=f"{obs.duration_ms:.0f} ms")

        # A signal is never normal behaviour, whatever the exit code says.
        if obs.signal is not None:
            return Judgement(
                Verdict.CRASH,
                signature=failure_signature(obs.stderr_preview, obs.stdout_preview),
                detail=f"signal {obs.signal}",
            )

        # A configured crash marker outranks everything below.
        if looks_like_crash(obs.stderr_preview, obs.stdout_preview, self.crash_patterns):
            return Judgement(
                Verdict.CRASH,
                signature=failure_signature(obs.stderr_preview, obs.stdout_preview),
                detail=f"exit {obs.exit_code} (matched a crash pattern)",
            )

        if obs.exit_code in self.expected_exit_codes:
            return Judgement(Verdict.OK)

        # Non-zero, no signal: did the SUT *refuse* the input, or did it break?
        if looks_like_rejection(obs.stderr_preview, obs.stdout_preview, self.rejection_patterns):
            return Judgement(
                Verdict.EXPECTED_REJECTION,
                detail=extract_exception_normalized(obs.stderr_preview, obs.stdout_preview),
            )

        return Judgement(
            Verdict.CRASH,
            signature=failure_signature(obs.stderr_preview, obs.stdout_preview),
            detail=f"exit {obs.exit_code}",
        )


class DifferentialOracle:
    """Multi-target oracle: do independent implementations agree?

    Agreement is compared in the order return code -> exception -> stdout, with
    both sides normalized the same way.
    """

    name = "differential"

    def __init__(
        self,
        banners: tuple[str, ...] = (),
        compare_stdout: bool = True,
        expected_exit_codes: Iterable[int] = (0,),
        rejection_patterns: Sequence[str] | None = None,
        crash_patterns: Sequence[str] | None = None,
    ) -> None:
        self.banners = banners
        self.compare_stdout = compare_stdout
        self._single = CrashOracle(expected_exit_codes, rejection_patterns, crash_patterns)

    def _fingerprint(self, obs: Observation) -> tuple:
        exc = normalize_exception_for_compare(
            extract_exception_normalized(obs.stderr_preview, obs.stdout_preview)
        )
        out = ""
        if self.compare_stdout:
            out = norm_text(filter_banners(obs.stdout_preview, self.banners))
        # Only the *class* of the exit code matters: engines pick different
        # non-zero codes for the same refusal.
        rc_class = 0 if obs.exit_code == 0 else 1
        return (rc_class, exc, out)

    def judge(self, observations: Sequence[Observation]) -> Judgement:
        if len(observations) < 2:
            return self._single.judge(observations)

        # A hard failure in any single target outranks a disagreement.
        for obs in observations:
            j = self._single.judge([obs])
            if j.verdict in (Verdict.CRASH, Verdict.TIMEOUT):
                return Judgement(j.verdict, j.signature, f"{obs.sut_id}: {j.detail}")

        singles = [self._single.judge([o]) for o in observations]

        # Every target refused the input. Engines word syntax errors
        # differently, so that is agreement, not a divergence.
        if all(j.verdict is Verdict.EXPECTED_REJECTION for j in singles):
            return Judgement(Verdict.EXPECTED_REJECTION, detail="all targets rejected")

        # Some accepted and some refused: that IS a real divergence.
        accepted = {o.sut_id for o, j in zip(observations, singles) if j.verdict is Verdict.OK}
        rejected = {o.sut_id for o, j in zip(observations, singles) if j.verdict is Verdict.EXPECTED_REJECTION}
        if accepted and rejected:
            return Judgement(
                Verdict.DIVERGENCE,
                signature=_divergence_signature(sorted(accepted), sorted(rejected), "acceptance"),
                detail=f"accepted by {sorted(accepted)}, rejected by {sorted(rejected)}",
            )

        fps = {o.sut_id: self._fingerprint(o) for o in observations}
        distinct = set(fps.values())
        if len(distinct) == 1:
            return Judgement(Verdict.OK)

        groups: dict[tuple, list[str]] = {}
        for sut_id, fp in fps.items():
            groups.setdefault(fp, []).append(sut_id)
        partition = sorted(sorted(v) for v in groups.values())
        return Judgement(
            Verdict.DIVERGENCE,
            signature=_divergence_signature(*partition, kind="output"),
            detail="output groups: " + " vs ".join("+".join(g) for g in partition),
        )


def _divergence_signature(*groups, kind: str = "output") -> str:
    from hashlib import sha256

    key = kind + "|" + "|".join("+".join(g) for g in groups)
    return "div-" + sha256(key.encode()).hexdigest()[:12]


def make_oracle(config: dict | None) -> Oracle:
    """Build an oracle from the `oracle:` block of spreadex.yaml."""
    config = config or {}
    kind = (config.get("type") or "crash").lower()
    expected = config.get("expected_exit_codes", [0])
    rejection = config.get("rejection_patterns")
    crash = config.get("crash_patterns")
    if kind in ("differential", "diff"):
        return DifferentialOracle(
            banners=tuple(config.get("banners", ())),
            compare_stdout=config.get("compare_stdout", True),
            expected_exit_codes=expected,
            rejection_patterns=rejection,
            crash_patterns=crash,
        )
    if kind == "crash":
        return CrashOracle(expected_exit_codes=expected, rejection_patterns=rejection,
                           crash_patterns=crash)
    raise ValueError(f"Unknown oracle type: {kind!r} (expected 'crash' or 'differential')")
