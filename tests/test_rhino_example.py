"""The golden pipeline as a test: grammar -> generators -> CC -> SpreadEx -> Rhino.

Needs a Rhino build (RHINO_JAR) and the three generators installed, so it is
marked `network` and deselected by default. This is the end-to-end check that
the architecture holds together on a real language runtime.
"""

import os
import shutil
from pathlib import Path

import pytest

from spreadex.core.campaign import Campaign
from spreadex.core.config import load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "rhino"

pytestmark = pytest.mark.network


@pytest.fixture
def rhino_project(tmp_path):
    if not os.environ.get("RHINO_JAR"):
        pytest.skip("set RHINO_JAR to a Rhino build to run the golden pipeline")
    if not shutil.which("java"):
        pytest.skip("java not available")
    dest = tmp_path / "rhino"
    shutil.copytree(EXAMPLE, dest,
                    ignore=shutil.ignore_patterns(".spreadex", "__pycache__"))
    cfg = load_config(dest / "spreadex.yaml")
    cfg.raw.setdefault("generation", {})["count"] = 30   # keep the test short
    cfg.budget.generation_s = 180
    cfg.budget.execution_s = 180
    return cfg


def test_golden_pipeline(rhino_project):
    cfg = rhino_project
    result = Campaign(cfg, log=lambda *_: None).run(jobs=4)

    # Every generator the config asks for contributed and was scored. Taken
    # from the config rather than written out here: a hardcoded list said
    # Grammarinator could not generate for months after it could.
    assert set(result.generator_scores) == set(cfg.generators)
    assert len(cfg.generators) == 4, "one grammar, four dialects -- that is the claim"
    assert all(0.0 <= v <= 1.0 for v in result.generator_scores.values())
    assert result.k_eff and result.k_eff > 1

    assert result.generated > 0 and result.executed > 0

    # Most generated JavaScript is invalid, and Rhino is right to refuse it.
    # Those must land in expected_rejection, not in the failure count.
    assert result.verdicts.get("expected_rejection", 0) > 0

    # Rhino 1.8.1 is mature and these grammars are simple, so the honest
    # expectation is no crashes. A crash here is either a real find or a
    # regression in the rejection patterns -- both worth failing on.
    assert result.verdicts.get("crash", 0) == 0, (
        "unexpected crashes: either Rhino genuinely broke, or oracle."
        "rejection_patterns no longer cover a Rhino diagnostic"
    )


def test_manifest_records_the_generators(rhino_project):
    import json

    result = Campaign(rhino_project, log=lambda *_: None).run(jobs=4)
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    assert manifest["corpus"]["generator_scores"]
    assert manifest["targets"][0]["command"][0] == "java"
