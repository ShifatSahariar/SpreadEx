"""The acceptance test: a built wheel, a scratch directory, nothing else.

Every other test in this suite imports spreadex from the source tree, which
means none of them can tell whether the thing we would actually ship works.
This one builds the wheel, installs it into an empty virtualenv, and runs the
journey from a directory outside both this repository and the research one --
then asserts that nothing it touched resolved back into either.

Marked `network` because building and installing reaches PyPI for build
dependencies. Run it with:

    pytest tests/test_clean_wheel_acceptance.py -m network
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.network

REPO = Path(__file__).resolve().parents[1]
#: Anything that resolving into these would mean the wheel is not standalone.
FORBIDDEN = ("Documents/RESEARCH/spreadex", "Documents/RESEARCH/SpreadEx-2026",
             "Documents/RESEARCH/ClusGram", str(REPO))


def run(cmd, cwd=None, env=None, timeout=900):
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=timeout)
    return proc


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """Build a wheel and install it into a virtualenv with nothing else in it."""
    work = tmp_path_factory.mktemp("acceptance")
    dist = work / "dist"
    build = run([sys.executable, "-m", "build", "--outdir", str(dist)], cwd=REPO)
    if build.returncode != 0:
        pytest.skip(f"cannot build a wheel here:\n{build.stderr[-2000:]}")

    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1, wheels

    venv = work / "venv"
    assert run([sys.executable, "-m", "venv", str(venv)]).returncode == 0
    pip = venv / "bin" / "pip"
    install = run([pip, "install", "--quiet", str(wheels[0])], timeout=1200)
    assert install.returncode == 0, install.stderr[-2000:]
    return venv / "bin" / "spreadex", work


def clean_env() -> dict:
    """No PYTHONPATH, no inherited pointers into either repository."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "SPREADEX_RESEARCH_REPO", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_the_wheel_installs_and_reports_its_own_version(installed):
    spreadex, _ = installed
    proc = run([spreadex, "--version"], env=clean_env())
    assert proc.returncode == 0
    assert "spreadex" in proc.stdout.lower()


def test_the_package_resolves_outside_both_repositories(installed):
    """A wheel that imports from the working tree is not a wheel."""
    spreadex, _ = installed
    with tempfile.TemporaryDirectory() as scratch:
        proc = run([spreadex, "doctor"], cwd=scratch, env=clean_env())
    text = proc.stdout + proc.stderr
    package_line = next((ln for ln in text.splitlines() if "package" in ln), "")
    assert package_line, text[:800]
    assert "site-packages" in package_line, package_line
    for bad in FORBIDDEN:
        assert bad not in package_line, f"resolved into {bad}: {package_line}"
    assert "working tree" not in text, "this is an editable install, not a wheel"


def test_the_bare_command_prints_help_outside_a_tty(installed):
    spreadex, _ = installed
    with tempfile.TemporaryDirectory() as scratch:
        proc = run([spreadex], cwd=scratch, env=clean_env())
    assert proc.returncode == 0
    assert "usage: spreadex" in proc.stdout


def test_the_demo_runs_a_real_campaign_from_a_scratch_directory(installed):
    """The acceptance criterion: a developer who knows nothing about this
    research installs the tool, types one command, and gets a real campaign."""
    spreadex, _ = installed
    with tempfile.TemporaryDirectory() as scratch:
        proc = run([spreadex, "demo"], cwd=scratch, env=clean_env(), timeout=1200)
        assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]

        out = proc.stdout
        assert "Executed" in out and "Rejected (expected)" in out

        project = Path(scratch) / "spreadex-demo"
        assert (project / "spreadex.yaml").is_file()
        assert (project / "calc.py").is_file(), "the SUT must ship in the wheel"
        assert (project / "calc.bnf").is_file(), "and so must the grammar"

        runs = sorted((project / ".spreadex" / "runs").iterdir())
        assert runs, "no run directory was written"
        manifest = json.loads((runs[-1] / "manifest.json").read_text())
        assert manifest["results"]["executed"] > 0

        # Nothing anywhere in the campaign's own record points back at a repo.
        recorded = json.dumps(manifest)
        for bad in FORBIDDEN:
            assert bad not in recorded, f"the manifest references {bad}"

        # ...and the results are readable back through the public commands.
        results = run([spreadex, "results"], cwd=project, env=clean_env())
        assert results.returncode == 0 and "Executed" in results.stdout

        replay = run([spreadex, "replay"], cwd=project, env=clean_env())
        assert replay.returncode == 0 and manifest["config_hash"] in replay.stdout

        exported = Path(scratch) / "campaign.zip"
        export = run([spreadex, "export", str(exported)], cwd=project, env=clean_env())
        assert export.returncode == 0 and exported.is_file()


def test_a_stranger_can_configure_and_run_their_own_sut(installed):
    """The second half of the acceptance criterion: not just our demo, but a
    system under test the tool has never seen, configured from scratch."""
    spreadex, _ = installed
    with tempfile.TemporaryDirectory() as scratch:
        project = Path(scratch) / "mine"
        (project / "seeds").mkdir(parents=True)
        (project / "seeds" / "a.txt").write_text("hello\n")
        (project / "seeds" / "b.txt").write_text("BAD input\n")
        (project / "mytool.py").write_text(
            "import sys\n"
            "t = open(sys.argv[1]).read()\n"
            "if 'BAD' in t:\n"
            "    print('mytool: refused', file=sys.stderr); sys.exit(1)\n"
            "print(len(t))\n"
        )
        (project / "spreadex.yaml").write_text(
            'sut:\n  command: ["python3", "./mytool.py", "{input}"]\n  timeout: 5s\n'
            "oracle:\n  type: crash\n"
            '  rejection_patterns: ["^mytool: refused"]\n'
            "generators: []\ncorpus: {path: ./seeds}\n"
            "budget: {generation: 10s, execution: 30s}\nseed: 42\n"
        )

        doctor = run([spreadex, "doctor"], cwd=project, env=clean_env())
        assert doctor.returncode == 0, doctor.stdout

        campaign = run([spreadex, "run"], cwd=project, env=clean_env(), timeout=600)
        assert campaign.returncode == 0, campaign.stdout[-2000:]
        assert "Rejected (expected) ... 1" in campaign.stdout, (
            "the SUT's own refusal must not be reported as a crash:\n"
            + campaign.stdout
        )
        assert "Crashes ............... 0" in campaign.stdout
