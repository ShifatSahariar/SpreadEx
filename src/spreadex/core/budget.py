"""Budget policy: how much of a finite resource each generator gets.

v0.1 ships uniform allocation only -- deliberately. A deterministic, explainable
policy is the correct default AND the honest baseline that an adaptive policy
(research track R2) must beat.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Clock:
    """A wall-clock budget. Nothing here estimates; it only measures."""

    total_s: float
    started_at: float = field(default_factory=time.perf_counter)

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.total_s - self.elapsed())

    def exhausted(self) -> bool:
        return self.remaining() <= 0.0

    def reset(self) -> None:
        self.started_at = time.perf_counter()


def uniform_allocation(generators: list[str], total_s: float) -> dict[str, float]:
    """Equal split. The baseline every adaptive policy is measured against."""
    if not generators:
        return {}
    share = total_s / len(generators)
    return {g: share for g in generators}


def proportional_allocation(
    generators: list[str],
    total_s: float,
    scores: dict[str, float],
    floor: float = 0.05,
) -> dict[str, float]:
    """Allocate in proportion to a selection signal, with a floor so that no
    generator is starved to zero on the strength of one noisy round.

    Not wired into the campaign loop yet -- it needs a second round to have
    scores to act on. Present so the adaptive work (R2) is a policy swap.
    """
    if not generators:
        return {}
    n = len(generators)
    if floor * n >= 1.0:
        return uniform_allocation(generators, total_s)

    vals = {g: max(0.0, scores.get(g, 0.0)) for g in generators}
    s = sum(vals.values())
    if s <= 0:
        return uniform_allocation(generators, total_s)

    reserved = floor * n
    free = 1.0 - reserved
    return {g: total_s * (floor + free * (v / s)) for g, v in vals.items()}
