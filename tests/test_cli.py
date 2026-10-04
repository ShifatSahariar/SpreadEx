"""The public command surface.

This is the contract: what a developer types and what comes back. Renames are
allowed to happen once and must keep the old name working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spreadex.cli.main import main as cli_main


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    """A real finished campaign, run once for the whole module.

    The demo project is the smallest honest end-to-end campaign we have, and
    using it here means these tests break if the demo breaks.
    """
    from spreadex.core.campaign import Campaign
    from spreadex.core.config import load_config
    from spreadex.demo import materialize

    project = materialize(tmp_path_factory.mktemp("cli") / "demo")
    config = load_config(project / "spreadex.yaml")
    # No generators: this fixture is about the CLI, not about generation, and a
    # pip install per test session would be a poor trade for the same coverage.
    config.generators = []
    Campaign(config).run(jobs=2)
    return project / "spreadex.yaml"


# ---------------------------------------------------- the command surface

def test_results_shows_the_latest_campaign(demo_run, capsys):
    """Someone who just ran a campaign wants to know how it went, not a table
    of every run they have ever done."""
    assert cli_main(["-c", str(demo_run), "results"]) == 0
    out = capsys.readouterr().out
    assert "Campaign" in out and "Executed" in out
    assert "Rejected (expected)" in out
    assert "RUN " not in out, "the history table is behind --all"


def test_results_all_lists_every_campaign(demo_run, capsys):
    assert cli_main(["-c", str(demo_run), "results", "--all"]) == 0
    out = capsys.readouterr().out
    assert "RUN" in out and "EXECUTED" in out


def test_report_still_works_and_is_hidden(demo_run, capsys):
    """Renamed, not removed: notes and scripts should not break over it."""
    assert cli_main(["-c", str(demo_run), "report"]) == 0
    assert "RUN" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        cli_main(["--help"])
    assert "report" not in capsys.readouterr().out.split("positional")[-1][:400]


def test_results_says_what_to_do_when_there_is_nothing(tmp_path, capsys):
    """An empty state is a signpost, not an error."""
    project = tmp_path / "p"
    project.mkdir()
    (project / "spreadex.yaml").write_text(
        'sut:\n  command: ["echo", "{input}"]\ngenerators: []\ncorpus: {path: .}\n')
    assert cli_main(["-c", str(project / "spreadex.yaml"), "results"]) == 0
    out = capsys.readouterr().out
    assert "No campaigns yet" in out and "spreadex demo" in out


def test_generators_status_matches_list(capsys):
    assert cli_main(["generators", "status"]) == 0
    status = capsys.readouterr().out
    assert cli_main(["generators", "list"]) == 0
    assert status == capsys.readouterr().out


def test_doctor_reports_where_this_spreadex_came_from(capsys):
    """The confusing failures are the ones where `spreadex` is not the
    spreadex you think it is."""
    from spreadex.cli import doctor

    rendered = "\n".join(c.render() for c in doctor.installation_checks())
    for expected in ("spreadex", "package", "python", "platform", "workbench UI"):
        assert expected in rendered, expected
