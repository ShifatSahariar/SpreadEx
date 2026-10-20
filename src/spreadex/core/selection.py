"""Generator selection by Cluster Coverage.

Opt-in (`selection: {by: cc, keep: N}`): after the diversity map is built over the
whole pool, keep the N configured generators that reached the most clusters, and
execute only inputs they produced. CC is still measured on the full pool, so the
scores of kept and dropped generators remain comparable.

Inputs that came from a non-generator source (the project's own corpus) are always
kept: selection compares generators, it does not discard the user's seeds. An input
that several generators produced survives if any producer was kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

#: Tie-break for equal Cluster Coverage: a fixed preference ranking computed from published evidence,
#: the per-generator mutation scores of the ICST 2026 study (replication package
#: doi:10.5281/zenodo.20071065, `data/Generator_Selection_Results/*/run_*/mutation_metrics.csv`).
#: Each family's score is the mean over its two evaluated configurations, averaged over 10 runs on each
#: of the six subjects. Mean mutation score: FuzzingBook 0.845 (best on all six subjects),
#: LLM-based 0.730 (GPT-4.1 prompting, the study's LLM-based generator; Fuzz4All stands in for that
#: family here), ISLa 0.675, Fandango 0.654. Grammarinator was not part of the study and follows the
#: generators with evidence; any other generator follows, by name.
PREFERENCE: tuple[str, ...] = ("fuzzingbook", "fuzz4all", "isla", "fandango", "grammarinator")


def _preference(generator: str) -> int:
    return PREFERENCE.index(generator) if generator in PREFERENCE else len(PREFERENCE)


@dataclass
class Selection:
    keep: int
    selected: list[str]
    dropped: list[str]
    scores: dict[str, float] = field(default_factory=dict)
    kept_inputs: int = 0
    dropped_inputs: int = 0

    def as_dict(self) -> dict:
        return {"by": "cc", "keep": self.keep, "selected": self.selected, "dropped": self.dropped,
                "scores": self.scores, "kept_inputs": self.kept_inputs,
                "dropped_inputs": self.dropped_inputs}

    def log_line(self) -> str:
        fmt = lambda gs: ", ".join(f"{g} {self.scores[g]:.2f}" for g in gs)
        total = len(self.selected) + len(self.dropped)
        return (f"  selected by cluster coverage: {fmt(self.selected)} "
                f"(kept {len(self.selected)} of {total}; dropped {fmt(self.dropped)}; "
                f"{self.kept_inputs} inputs to execute)")


def choose(scores: Mapping[str, float], configured: Iterable[str], keep: int) -> tuple[list[str], list[str]] | None:
    """The `keep` configured generators with the highest CC, and the rest. Equal CC is resolved by the
    evidence-based PREFERENCE ranking, then by name.

    None when there is nothing to choose: no more producing generators than `keep`.
    """
    candidates = [g for g in dict.fromkeys(configured) if g in scores]
    if len(candidates) <= keep:
        return None
    ranked = sorted(candidates, key=lambda g: (-scores[g], _preference(g), g))
    return ranked[:keep], ranked[keep:]


def apply(ordered: Sequence, origins: Mapping[str, set[str]], dropped: Iterable[str]) -> list:
    """`ordered` without the inputs that only dropped generators produced; order kept."""
    gone = set(dropped)
    return [it for it in ordered if not origins.get(it.blob_hash, {it.generator}) <= gone]
