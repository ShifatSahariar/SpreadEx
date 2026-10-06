"""Persistent local corpus: SQLite metadata + a content-addressed blob store.

Content addressing is the point. One program produced by Fandango *and*
Grammarinator, executed against Rhino v1 *and* GraalJS v2, is one blob with
four execution rows -- which is what later makes cold-start -> warm-start
regression testing possible without a separate bookkeeping layer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from ..exec.observation import Observation
from ..exec.oracle import Judgement

SCHEMA_VERSION = "1"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_state_dir(path: Path) -> Path:
    """Create `.spreadex/` and keep it out of version control.

    Called from everywhere that might create the directory first -- the corpus
    store, and the UI writing its token -- because whichever gets there first
    must leave the .gitignore behind. It holds corpora, crash inputs and the UI
    token, none of which belong in anyone's history.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text(
            "# SpreadEx local state: corpora, runs and the UI token.\n"
            "# None of this belongs in version control.\n*\n"
        )
    return path


class CorpusStore:
    """Everything SpreadEx remembers about one project, in `.spreadex/`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.runs_dir = self.root / "runs"
        self.db_path = self.root / "corpus.db"
        self._conn: sqlite3.Connection | None = None

    # ---------------------------------------------------------------- lifecycle

    def open(self) -> "CorpusStore":
        ensure_state_dir(self.root)
        self.blobs.mkdir(exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)
        (self.root / "cache").mkdir(exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._migrate()
        self._conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
            (SCHEMA_VERSION,),
        )
        self._conn.commit()
        return self

    def _migrate(self) -> None:
        """Add columns introduced after a store was first created.

        A corpus outlives the version that made it, so opening an older one
        must not fail -- the accumulated history is the point.
        """
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(failures)")}
        if "example_stderr" not in existing:
            self._conn.execute("ALTER TABLE failures ADD COLUMN example_stderr TEXT")
        run_cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "status" not in run_cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN status TEXT")
            self._conn.execute(
                "UPDATE runs SET status = CASE WHEN finished_at IS NULL THEN 'aborted' "
                "ELSE 'finished' END")
        if "origin" not in run_cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN origin TEXT")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "CorpusStore":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("CorpusStore is not open; use `with CorpusStore(root) as store:`")
        return self._conn

    # ------------------------------------------------------------------- blobs

    def _blob_path(self, blob_hash: str) -> Path:
        return self.blobs / blob_hash[:2] / blob_hash

    def put_blob(self, data: bytes) -> str:
        """Store bytes, return their hash. Writing the same bytes twice is free."""
        h = hash_bytes(data)
        path = self._blob_path(h)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic: a reader never sees a partial blob
        return h

    def get_blob(self, blob_hash: str) -> bytes:
        return self._blob_path(blob_hash).read_bytes()

    def blob_path(self, blob_hash: str) -> Path:
        return self._blob_path(blob_hash)

    # ------------------------------------------------------------------ inputs

    def add_input(
        self,
        data: bytes,
        generator: str,
        grammar_version: str | None = None,
        valid: bool | None = None,
        gen_cost_ms: float | None = None,
    ) -> str:
        h = self.put_blob(data)
        now = utcnow()
        self.conn.execute(
            """INSERT INTO inputs(blob_hash, generator, grammar_version, generated_at,
                                  valid, gen_cost_ms, size_bytes)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(blob_hash) DO UPDATE SET
                   valid = COALESCE(excluded.valid, inputs.valid)""",
            (h, generator, grammar_version, now, _b(valid), gen_cost_ms, len(data)),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO input_origins(blob_hash, generator, discovered_at) VALUES (?,?,?)",
            (h, generator, now),
        )
        return h

    def set_validity(self, blob_hash: str, valid: bool) -> None:
        self.conn.execute("UPDATE inputs SET valid=? WHERE blob_hash=?", (_b(valid), blob_hash))

    def generators_of(self, blob_hash: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT generator FROM input_origins WHERE blob_hash=? ORDER BY generator", (blob_hash,)
        ).fetchall()
        return [r["generator"] for r in rows]

    def count_inputs(self, valid_only: bool = False) -> int:
        q = "SELECT COUNT(*) c FROM inputs" + (" WHERE valid=1" if valid_only else "")
        return self.conn.execute(q).fetchone()["c"]

    def iter_inputs(self, valid_only: bool = False) -> Iterator[sqlite3.Row]:
        q = "SELECT * FROM inputs" + (" WHERE valid=1" if valid_only else "") + " ORDER BY generated_at"
        yield from self.conn.execute(q)

    # -------------------------------------------------------------------- runs

    def start_run(
        self,
        run_id: str,
        config_hash: str,
        seed: int | None = None,
        gen_budget_s: float | None = None,
        exec_budget_s: float | None = None,
        signal_name: str | None = None,
        origin: str | None = None,
    ) -> Path:
        self.conn.execute(
            """INSERT INTO runs(run_id, started_at, config_hash, seed,
                                gen_budget_s, exec_budget_s, signal_name, status, origin)
               VALUES (?,?,?,?,?,?,?,'running',?)""",
            (run_id, utcnow(), config_hash, seed, gen_budget_s, exec_budget_s, signal_name,
             origin),
        )
        self.conn.commit()
        d = self.runs_dir / run_id
        (d / "logs").mkdir(parents=True, exist_ok=True)
        return d

    def unique_run_id(self, base: str) -> str:
        """`base`, or `base-2`, `base-3`... if a run already has it.

        Ids are timestamps to the second, so two campaigns started in the same second
        (a CI script, a retry) would otherwise collide on the UNIQUE key.
        """
        candidate, n = base, 1
        while self.conn.execute("SELECT 1 FROM runs WHERE run_id=?", (candidate,)).fetchone() \
                or (self.runs_dir / candidate).exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def finish_run(self, run_id: str, manifest_hash: str | None = None,
                   status: str = "finished") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, manifest_hash=?, status=? WHERE run_id=?",
            (utcnow(), manifest_hash, status, run_id),
        )
        self.conn.commit()

    def set_status(self, run_id: str, status: str) -> None:
        self.conn.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
        self.conn.commit()

    def mark_abandoned(self) -> None:
        """Runs still 'running' when nobody holds the project lock died without
        finishing. Call only while holding, or having checked, the lock."""
        self.conn.execute("UPDATE runs SET status='aborted' WHERE status='running'")
        self.conn.commit()

    def run_blob_bytes(self, run_id: str) -> int:
        """Bytes that deleting this run would free: inputs only it executed."""
        row = self.conn.execute(
            """SELECT COALESCE(SUM(i.size_bytes), 0) b FROM inputs i
               WHERE i.blob_hash IN (SELECT blob_hash FROM executions WHERE run_id=?)
                 AND NOT EXISTS (SELECT 1 FROM executions e
                                 WHERE e.blob_hash=i.blob_hash AND e.run_id<>?)""",
            (run_id, run_id),
        ).fetchone()
        return int(row["b"])

    def delete_run(self, run_id: str) -> dict:
        """Forget one run and reclaim what only it used.

        Inputs are shared: `input_origins` is keyed by (blob, generator), not by
        run, so it is never deleted per run. An input goes only when this run
        executed it and no other run did, and no surviving failure points at it.
        Inputs that were generated but never executed by any run are corpus, not
        run output, and stay.
        """
        c = self.conn
        if not c.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
            raise KeyError(run_id)
        candidates = [r["blob_hash"] for r in c.execute(
            "SELECT DISTINCT blob_hash FROM executions WHERE run_id=?", (run_id,))]
        c.commit()  # close any implicit transaction so BEGIN starts ours
        try:
            c.execute("BEGIN")
            c.execute("DELETE FROM executions WHERE run_id=?", (run_id,))
            # Failures first seen here: re-point at the earliest later sighting, or drop.
            for f in c.execute("SELECT signature FROM failures WHERE first_seen_run=? "
                               "OR last_seen_run=?", (run_id, run_id)).fetchall():
                sig = f["signature"]
                seen = c.execute(
                    """SELECT e.run_id, r.started_at, COUNT(*) n FROM executions e
                       JOIN runs r ON r.run_id=e.run_id WHERE e.signature=?
                       GROUP BY e.run_id ORDER BY r.started_at""", (sig,)).fetchall()
                if not seen:
                    c.execute("DELETE FROM failures WHERE signature=?", (sig,))
                    continue
                example = c.execute("SELECT blob_hash FROM executions WHERE signature=? "
                                    "ORDER BY run_id, rank LIMIT 1", (sig,)).fetchone()
                c.execute(
                    """UPDATE failures SET first_seen_run=?, first_seen_at=?, last_seen_run=?,
                           occurrences=?,
                           example_blob_hash=CASE WHEN example_blob_hash IN
                               (SELECT blob_hash FROM executions WHERE signature=?)
                               THEN example_blob_hash ELSE ? END
                       WHERE signature=?""",
                    (seen[0]["run_id"], seen[0]["started_at"], seen[-1]["run_id"],
                     sum(r["n"] for r in seen), sig, example["blob_hash"], sig))
            c.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            orphans = []
            for h in candidates:
                used = c.execute(
                    """SELECT 1 FROM executions WHERE blob_hash=?
                       UNION SELECT 1 FROM failures
                       WHERE example_blob_hash=? OR minimized_blob_hash=? LIMIT 1""",
                    (h, h, h)).fetchone()
                if not used:
                    orphans.append(h)
            freed = 0
            for h in orphans:
                row = c.execute("SELECT size_bytes FROM inputs WHERE blob_hash=?", (h,)).fetchone()
                freed += (row["size_bytes"] or 0) if row else 0
                c.execute("DELETE FROM inputs WHERE blob_hash=?", (h,))  # origins cascade
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        for h in orphans:
            self._blob_path(h).unlink(missing_ok=True)
        d = self.run_dir(run_id)
        if d.exists():
            freed += sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
            shutil.rmtree(d, ignore_errors=True)
        return {"run_id": run_id, "inputs_removed": len(orphans), "bytes_freed": freed}

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def latest_run_id(self) -> str | None:
        row = self.conn.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return row["run_id"] if row else None

    def list_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # -------------------------------------------------------------- executions

    def record_execution(
        self,
        run_id: str,
        blob_hash: str,
        rank: int,
        observations: Sequence[Observation],
        judgement: Judgement,
    ) -> None:
        stderr_sample = next(
            (o.stderr_preview for o in observations if o.stderr_preview), None
        )
        for obs in observations:
            self.conn.execute(
                """INSERT OR REPLACE INTO executions(
                       run_id, blob_hash, rank, sut_id, sut_version, exit_code, signal,
                       timed_out, duration_ms, stdout_hash, stderr_hash,
                       verdict, signature, detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, blob_hash, rank, obs.sut_id, obs.sut_version,
                    obs.exit_code, obs.signal, int(obs.timed_out), obs.duration_ms,
                    obs.stdout_hash, obs.stderr_hash,
                    judgement.verdict.value, judgement.signature, judgement.detail,
                ),
            )
        if judgement.is_failure and judgement.signature:
            self._record_failure(run_id, blob_hash, judgement, stderr_sample)

    def _record_failure(self, run_id: str, blob_hash: str, j: Judgement,
                        stderr_sample: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO failures(signature, verdict, first_seen_run, first_seen_at,
                                    last_seen_run, occurrences, example_blob_hash, detail,
                                    example_stderr)
               VALUES (?,?,?,?,?,1,?,?,?)
               ON CONFLICT(signature) DO UPDATE SET
                   occurrences    = failures.occurrences + 1,
                   last_seen_run  = excluded.last_seen_run,
                   example_stderr = COALESCE(failures.example_stderr, excluded.example_stderr)""",
            (j.signature, j.verdict.value, run_id, utcnow(), run_id, blob_hash, j.detail,
             stderr_sample),
        )

    def run_summary(self, run_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            """SELECT verdict, COUNT(DISTINCT blob_hash) c
               FROM executions WHERE run_id=? GROUP BY verdict""",
            (run_id,),
        ).fetchall()
        return {r["verdict"]: r["c"] for r in rows}

    def signatures_in_run(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT signature, verdict, COUNT(DISTINCT blob_hash) n, MIN(blob_hash) example
               FROM executions
               WHERE run_id=? AND signature IS NOT NULL AND verdict IN
                     ('crash','timeout','divergence')
               GROUP BY signature, verdict ORDER BY n DESC""",
            (run_id,),
        ).fetchall()

    def new_signatures(self, run_id: str) -> list[str]:
        """Signatures whose very first sighting was this run -- the CI signal."""
        rows = self.conn.execute(
            "SELECT signature FROM failures WHERE first_seen_run=?", (run_id,)
        ).fetchall()
        return [r["signature"] for r in rows]

    def write_results_jsonl(self, run_id: str) -> Path:
        path = self.run_dir(run_id) / "results.jsonl"
        rows = self.conn.execute(
            "SELECT * FROM executions WHERE run_id=? ORDER BY rank, sut_id", (run_id,)
        ).fetchall()
        with path.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(dict(r)) + "\n")
        return path

    def commit(self) -> None:
        self.conn.commit()


def _b(v: bool | None) -> int | None:
    return None if v is None else int(v)
