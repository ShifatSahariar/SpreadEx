"""Generator adapters.

Every adapter runs its generator as a subprocess in that generator's own
environment. SpreadEx never imports a generator: ISLa is GPL-3.0, Fandango is
EUPL-1.2, and their dependency pins conflict. The tests that actually generate
are marked `network` (they need an installed generator) and deselected by
default.
"""

from pathlib import Path

import pytest

from spreadex.generators import GeneratorError, GeneratorManager
from spreadex.generators.adapters import ADAPTERS, generate

RESEARCH_GRAMMARS = Path(__file__).resolve().parents[2] / "spreadex" / "examples" / "rhino" / "grammars"


def test_every_catalog_generator_has_an_adapter():
    from spreadex.generators import load_catalog

    assert set(load_catalog()) == set(ADAPTERS), "catalog and adapters drifted apart"


def test_unknown_generator_lists_the_available_ones(tmp_path):
    (tmp_path / "g.bnf").write_text("<start> ::= \"x\"")
    with pytest.raises(GeneratorError, match="No adapter for generator"):
        generate("nonesuch", tmp_path / "g.bnf", 1)


def test_missing_grammar_names_the_path(tmp_path):
    with pytest.raises(GeneratorError, match="Grammar not found"):
        generate("fuzzingbook", tmp_path / "absent.py", 1)


def test_grammarinator_needs_a_grammar_header(tmp_path):
    """Grammarinator names the class it builds after the grammar, so a .g4
    without a `grammar <Name>;` header cannot be compiled."""
    g = tmp_path / "g.g4"
    g.write_text("start : 'x' ;")
    with pytest.raises(GeneratorError, match="no `grammar <Name>;` header"):
        generate("grammarinator", g, 1)


def test_grammarinator_needs_a_parser_rule_to_start_from(tmp_path):
    g = tmp_path / "g.g4"
    g.write_text("grammar X;\nSTART : 'x' ;")
    with pytest.raises(GeneratorError, match="No parser rule found"):
        generate("grammarinator", g, 1)


def test_adapters_do_not_import_generators_into_this_process():
    """The subprocess boundary is the licensing and dependency firewall."""
    import sys

    for module in ("isla", "isla.solver", "fandango"):
        assert module not in sys.modules, f"{module} was imported into the SpreadEx process"


def test_python_resolution_prefers_the_isolated_environment(tmp_path):
    mgr = GeneratorManager(cache_dir=tmp_path)
    # With no environment present it falls back to the host interpreter.
    assert mgr.python_for("isla") == __import__("sys").executable
    env_bin = mgr.env_python("isla")
    env_bin.parent.mkdir(parents=True, exist_ok=True)
    env_bin.write_text("#!/bin/sh\n")
    env_bin.chmod(0o755)
    assert mgr.python_for("isla") == str(env_bin)


@pytest.mark.network
@pytest.mark.parametrize("generator,grammar", [
    ("fuzzingbook", "rhino.fuzzingbook.py"),
    ("fandango", "rhino.fan"),
    ("isla", "rhino.bnf"),
])
def test_real_generation_produces_javascript(generator, grammar):
    """End to end against a real generator. Needs it installed."""
    path = RESEARCH_GRAMMARS / grammar
    if not path.exists():
        pytest.skip(f"grammar {grammar} not present")
    mgr = GeneratorManager()
    if not mgr.status(generator).installed:
        pytest.skip(f"{generator} not installed")

    batch = generate(generator, path, count=5, seed=42, timeout=180, manager=mgr)
    assert batch.inputs, f"{generator} produced nothing"
    assert batch.cost_per_input_ms > 0
    text = batch.inputs[0].decode("utf-8", errors="replace")
    assert text.strip(), "generated an empty input"


def test_isla_adapter_raises_both_caps():
    """Regression: `isla solve -n 150` returns 10 inputs unless -f is raised
    too, because free instantiations default to 10."""
    import inspect

    from spreadex.generators import adapters

    src = inspect.getsource(adapters.generate_isla)
    assert '"-n"' in src and '"-f"' in src, "ISLa must raise -n and -f together"


def test_isla_passes_grammar_positionally():
    """-g takes grammar TEXT, not a path; files are positional."""
    import inspect

    from spreadex.generators import adapters

    src = inspect.getsource(adapters.generate_isla)
    assert '"-g"' not in src, "-g would make ISLa parse the path as a grammar"


def test_partial_results_are_kept_when_the_budget_runs_out(tmp_path, monkeypatch):
    """A generator that ran out of budget has usually written something, and
    keeping it beats discarding the work. Rich real-world grammars routinely
    exhaust FuzzingBook's budget while still yielding inputs."""
    from spreadex.generators import adapters

    def slow_adapter(mgr, grammar, n, out_dir, seed, timeout):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "a.txt").write_bytes(b"produced before the deadline")
        raise GeneratorError("exceeded its generation budget")

    monkeypatch.setitem(adapters.ADAPTERS, "fuzzingbook", slow_adapter)
    g = tmp_path / "g.bnf"
    g.write_text('<start> ::= "x"')
    batch = adapters.generate("fuzzingbook", g, count=10, timeout=1)
    assert batch.partial and len(batch.inputs) == 1


def test_a_generator_that_produced_nothing_still_fails(tmp_path, monkeypatch):
    """Partial results must not turn a hard failure into a silent success."""
    from spreadex.generators import adapters

    def failing_adapter(mgr, grammar, n, out_dir, seed, timeout):
        raise GeneratorError("could not start")

    monkeypatch.setitem(adapters.ADAPTERS, "fuzzingbook", failing_adapter)
    g = tmp_path / "g.bnf"
    g.write_text('<start> ::= "x"')
    with pytest.raises(GeneratorError, match="could not start"):
        adapters.generate("fuzzingbook", g, count=10, timeout=1)


def test_emitted_fuzzingbook_grammars_disable_ebnf_conversion(tmp_path):
    """convert_ebnf_grammar would read a literal '+' after a nonterminal as an
    operator, so SpreadEx-emitted grammars carry a marker that skips it."""
    from spreadex.grammar import parse_bnf, render

    g = parse_bnf('<start> ::= <id> "++;"\n<id> ::= "x"')
    text = render(g, "fuzzingbook", "t")
    assert "SPREADEX_PURE_BNF = True" in text
