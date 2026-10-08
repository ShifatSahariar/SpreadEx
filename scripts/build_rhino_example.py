"""Assemble the Rhino example's grammars and recorded Fuzz4All corpus from a ClusGram checkout.

    python scripts/build_rhino_example.py --clusgram /path/to/ClusGram

Copies, unchanged:
  subjects/rhino/grammars/fandango/rhino.fan            -> grammars/fandango/rhino.fan
  subjects/rhino/grammars/grammarinator/rhino.g4        -> grammars/grammarinator/rhino.g4
  subjects/rhino/grammars/fuzz4all/{documentation.md, example_code.js} -> grammars/fuzz4all/
and records the first N inputs of experiments/generated_inputs/rhino/fuzz4all/run_01 (in that
run's manifest order) as a SpreadEx recording under recorded/fuzz4all/, verifying each file
against the run's own sha256. PROVENANCE.md lists every source path and checksum.

Rerunning it reproduces the same files byte for byte; it refuses to overwrite a recording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "spreadex" / "demo" / "rhino"
sys.path.insert(0, str(ROOT / "src"))

GRAMMARS = {
    "subjects/rhino/grammars/fandango/rhino.fan": "grammars/fandango/rhino.fan",
    "subjects/rhino/grammars/grammarinator/rhino.g4": "grammars/grammarinator/rhino.g4",
    "subjects/rhino/grammars/fuzz4all/documentation.md": "grammars/fuzz4all/documentation.md",
    "subjects/rhino/grammars/fuzz4all/example_code.js": "grammars/fuzz4all/example_code.js",
}
RUN = "experiments/generated_inputs/rhino/fuzz4all/run_01"
SUMMARY = "repro_data/generated_inputs/rhino/fuzz4all/run_01/reports/generation_summary.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from spreadex.generators.recorded import write

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--clusgram", required=True, type=Path)
    ap.add_argument("--count", type=int, default=100)
    args = ap.parse_args()
    cg = args.clusgram.resolve()

    rows = ["# Provenance of the Rhino example's grammars and recorded corpus", "",
            "Copied unchanged from the ClusGram research artifact by `scripts/build_rhino_example.py`.", "",
            "| File here | ClusGram source | sha256 |", "|---|---|---|"]
    for src, dst in GRAMMARS.items():
        target = DEST / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cg / src, target)
        assert sha(target) == sha(cg / src)
        rows.append(f"| `{dst}` | `{src}` | `{sha(target)}` |")

    manifest = json.loads((cg / RUN / "input_manifest.json").read_text())
    chosen = manifest[:args.count]
    inputs = []
    for e in chosen:
        data = (cg / RUN / "all_inputs" / e["filename"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != e["sha256"]:
            sys.exit(f"{e['filename']} does not match the ClusGram manifest's sha256")
        inputs.append(data)
    summary = json.loads((cg / SUMMARY).read_text())[0]
    provenance = {
        "source": "ClusGram research artifact, Fuzz4All baseline (the authors' artifact)",
        "run": "rhino/fuzz4all/run_01",
        "selection": f"first {len(inputs)} of {len(manifest)} inputs, in the run's manifest order",
        "source_manifest_sha256": sha(cg / RUN / "input_manifest.json"),
        "source_input_ids": [chosen[0]["input_id"], chosen[-1]["input_id"]],
        "model": "gpt-4.1-mini (stated by the author; not recorded in the source artifact)",
        "upstream": "fuzz4all@0bf42fe with the ClusGram study patch (stated, not observed)",
        "whole_run": {"requested": summary["total_requested"], "generated": summary["total_generated"],
                      "token_cost": summary["token_cost"], "wall_time_s": round(summary["wall_time_seconds"], 1)},
        "sut_at_generation": "Rhino 1.8.1-SNAPSHOT (ClusGram's pinned build), not the Rhino this example runs",
        "note": "Generated before this campaign. Replaying it reproduces these inputs exactly; it does "
                "not regenerate them, and an LLM would not regenerate them identically.",
    }
    write(DEST / "recorded" / "fuzz4all", "fuzz4all", inputs, provenance, suffix=".js")
    rows += ["", f"`recorded/fuzz4all/`: the first {len(inputs)} inputs of `{RUN}` "
             f"(manifest sha256 `{provenance['source_manifest_sha256']}`), each verified against that "
             f"manifest. Model: {provenance['model']}.", ""]
    (DEST / "grammars" / "PROVENANCE.md").write_text("\n".join(rows) + "\n")
    print(f"wrote {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
