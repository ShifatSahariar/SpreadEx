"""How generation budget is spent, and what the campaign records about it.

The headline claim -- which generator deserves the next budget -- is not
answerable unless what each generator was *given* is recorded alongside what
it produced. On this project's own JavaScript grammar, asking four generators
for 150 inputs each cost Fandango 2.5s and ISLa 44.8s: an 18x difference
hidden behind an identical input count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spreadex.core.config import ConfigError, load_config
from spreadex.core.sources import GenerationStats


def write(tmp_path: Path, generation: str) -> Path:
    cfg = tmp_path / "spreadex.yaml"
    cfg.write_text(
        'sut:\n  command: ["echo", "{input}"]\noracle: {type: crash}\n'
        "generators: [fuzzingbook]\ngrammar: {source: g.bnf}\n"
        f"{generation}"
        "budget: {generation: 60s, execution: 10s}\n"
    )
    (tmp_path / "g.bnf").write_text('<start> ::= "x"\n')
    return cfg


# ------------------------------------------------------------------ config

def test_count_is_the_default_so_existing_projects_are_unchanged(tmp_path):
    config = load_config(write(tmp_path, "generation:\n  count: 150\n"))
    assert (config.raw["generation"].get("mode") or "count") == "count"


def test_time_mode_loads(tmp_path):
    config = load_config(write(tmp_path, "generation:\n  mode: time\n  per_generator: 30s\n"))
    assert config.raw["generation"]["mode"] == "time"


def test_an_unknown_mode_names_both_and_says_what_each_is_for(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, "generation:\n  mode: fastest\n"))
    message = str(exc.value)
    assert "'count'" in message and "'time'" in message
    assert "reproducible" in message and "comparable" in message


def test_a_config_cannot_ask_for_both(tmp_path):
    """Carrying a count and a time budget does not say which was honoured."""
    with pytest.raises(ConfigError) as exc:
        load_config(write(tmp_path, "generation:\n  mode: time\n  count: 150\n"))
    assert "ignores `generation.count`" in str(exc.value)


# ------------------------------------------------------------ what is recorded

def test_stats_record_what_was_asked_for_and_what_it_cost():
    st = GenerationStats(generator="isla", mode="time", requested_seconds=30.0,
                         elapsed_s=29.4, produced=88, cap=20000)
    d = st.as_dict()
    assert d["mode"] == "time"
    assert d["requested_seconds"] == 30.0 and d["requested_count"] is None
    assert d["elapsed_s"] == 29.4 and d["produced"] == 88
    assert d["throughput_per_s"] == pytest.approx(88 / 29.4, rel=1e-3)
    assert d["hit_cap"] is False


def test_throughput_is_zero_rather_than_a_crash_when_nothing_ran():
    assert GenerationStats(generator="g", mode="time").throughput_per_s == 0.0


def test_a_generator_that_produced_nothing_still_records_what_it_was_given():
    """ISLa produced nothing in 30s on the JavaScript grammar. That is a
    result about ISLa at that budget, and losing it would make the run look
    like ISLa was never asked."""
    st = GenerationStats(generator="isla", mode="time", requested_seconds=30.0)
    assert st.as_dict()["requested_seconds"] == 30.0
    assert st.as_dict()["produced"] == 0


# ------------------------------------------------------- the campaign's report

def test_the_report_states_the_basis_of_every_comparison():
    """A CC table with no stated basis invites the reader to assume fairness."""
    source = Path("src/spreadex/cli/main.py").read_text()
    assert "EQUAL TIME" in source and "EQUAL INPUT COUNT" in source
    assert "not resource-fair" in source


def test_the_report_warns_when_cc_is_partly_a_volume_count():
    """CC is pool-relative. A generator supplying most of the pool touches most
    clusters almost by construction -- equal-time budgeting makes that MORE
    likely, not less, and the tool has to say so."""
    from spreadex.cli.main import _warn_if_cc_is_really_volume

    class R:
        generator_counts = {"grammarinator": 20000, "fandango": 1330, "fuzzingbook": 209}

    import io
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        _warn_if_cc_is_really_volume(R(), sum(R.generator_counts.values()))
    text = out.getvalue()
    assert "grammarinator" in text and "93%" in text
    assert "throughput ranking" in text


def test_no_warning_when_the_pool_is_balanced():
    from spreadex.cli.main import _warn_if_cc_is_really_volume

    class R:
        generator_counts = {"a": 150, "b": 150, "c": 150}

    import io
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        _warn_if_cc_is_really_volume(R(), 450)
    assert out.getvalue() == ""


def test_the_budget_error_does_not_give_count_advice_in_time_mode():
    """`lower generation.count` names a setting that does not exist under
    mode: time."""
    source = Path("src/spreadex/generators/adapters.py").read_text()
    assert "per_generator under mode: time" in source
