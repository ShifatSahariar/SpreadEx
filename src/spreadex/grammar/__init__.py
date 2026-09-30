"""One grammar in, every generator's dialect out.

Generators speak different notations -- FuzzingBook wants a Python dict, ISLa
plain BNF, Fandango BNF with EBNF operators and regex terminals -- so testing
one system with several of them has meant maintaining several grammars that
must be kept in step by hand. This package derives them from one source, and
reports what each generator can and cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .desugar import desugar
from .diagnose import Expressibility, Finding, Report, Severity, diagnose, expressibility
from .ir import Feature, Grammar
from .parse import GrammarError, load, parse_bnf, parse_fuzzingbook
from .render import EXTENSIONS, RENDERERS, RenderError, render

__all__ = [
    "Grammar", "Feature", "GrammarError", "RenderError",
    "load", "parse_bnf", "parse_fuzzingbook", "desugar", "render",
    "diagnose", "expressibility", "Report", "Finding", "Severity", "Expressibility",
    "adapt", "AdaptResult", "EXTENSIONS", "RENDERERS",
]


@dataclass
class AdaptResult:
    grammar: Grammar
    report: Report
    written: dict[str, Path] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    risks: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok and bool(self.written)


def adapt(
    source: str | Path,
    generators: list[str],
    out_dir: str | Path,
    start: str | None = None,
    stem: str | None = None,
) -> AdaptResult:
    """Derive a grammar for each generator from one source file.

    Errors in the source stop the whole adaptation -- emitting dialects from a
    grammar known to be broken only moves the failure somewhere less obvious.
    A generator that cannot express the grammar is skipped with its reason; the
    others are still written.
    """
    source = Path(source)
    grammar = load(source, start=start)
    report = diagnose(grammar)
    result = AdaptResult(grammar=grammar, report=report)
    if not report.ok:
        return result

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or source.stem

    for generator in generators:
        if generator not in RENDERERS:
            result.skipped[generator] = (
                f"SpreadEx cannot emit {generator}'s dialect yet "
                f"(it can emit: {', '.join(sorted(RENDERERS))})"
            )
            continue
        exp = expressibility(grammar, generator)
        if exp.risks:
            result.risks[generator] = exp.risks
        if not exp.usable:
            result.skipped[generator] = "; ".join(exp.blockers) or "not expressible"
            continue
        try:
            text = render(grammar, generator, source.name)
        except RenderError as exc:
            result.skipped[generator] = str(exc)
            continue
        path = out_dir / f"{stem}{EXTENSIONS[generator]}"
        path.write_text(text)
        result.written[generator] = path

    return result
