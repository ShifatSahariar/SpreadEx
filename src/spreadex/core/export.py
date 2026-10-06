"""Package a finished run so someone else can look at it and reproduce it.

Shared by `spreadex export` and the UI's Export action, so the zip means the same thing from both.
Contains the run's manifest and results, the project's spreadex.yaml, and the actual inputs behind
every failure -- a manifest that names a hash nobody else can resolve is not a reproduction.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from ..corpus.store import CorpusStore


class ExportError(Exception):
    """The run cannot be exported; the message says why."""


def build_export(config, run_id: str | None, out: Path) -> tuple[str, Path]:
    out = Path(out).resolve()
    with CorpusStore(config.state_dir) as store:
        run_id = run_id or store.latest_run_id()
        if not run_id:
            raise ExportError("no runs to export")
        run_dir = store.run_dir(run_id)
        if not run_dir.is_dir():
            raise ExportError(f"no run {run_id!r}. `spreadex results --all` lists them.")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "campaign"
        stage.mkdir()
        shutil.copytree(run_dir, stage / "run", dirs_exist_ok=True)
        shutil.copy2(config.project_root / "spreadex.yaml", stage / "spreadex.yaml")
        with CorpusStore(config.state_dir) as store:
            rows = store.conn.execute(
                """SELECT DISTINCT blob_hash, signature, verdict FROM executions
                   WHERE run_id=? AND verdict IN ('crash','timeout','divergence')""",
                (run_id,),
            ).fetchall()
            if rows:
                fdir = stage / "failing_inputs"
                fdir.mkdir()
                index = []
                for r in rows:
                    data = store.get_blob(r["blob_hash"])
                    fname = f"{r['verdict']}-{(r['signature'] or 'none')[:12]}-{r['blob_hash'][:8]}"
                    (fdir / fname).write_bytes(data)
                    index.append({"file": fname, **dict(r)})
                (fdir / "index.json").write_text(json.dumps(index, indent=2))
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in stage.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(stage))
    return run_id, out
