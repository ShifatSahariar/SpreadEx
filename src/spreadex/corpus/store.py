"""Persistent local corpus: SQLite metadata + a content-addressed blob store.

Content addressing is the point. One program produced by Fandango *and*
Grammarinator, executed against Rhino v1 *and* GraalJS v2, is one blob with
four execution rows -- which is what later makes cold-start -> warm-start
regression testing possible without a separate bookkeeping layer.
"""

from __future__ import annotations

import hashlib
import json
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
        self.root.mkdir(parents=True, exist_ok=True)
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
    ) -> Path:
        self.conn.execute(
            """INSERT INTO runs(run_id, started_at, config_hash, seed,
                                gen_budget_s, exec_budget_s, signal_name)
               VALUES (?,?,?,?,?,?,?)""",
            (run_id, utcnow(), config_hash, seed, gen_budget_s, exec_budget_s, signal_name),
        )
        self.conn.commit()
        d = self.runs_dir / run_id
        (d / "logs").mkdir(parents=True, exist_ok=True)
        return d

    def finish_run(self, run_id: str, manifest_hash: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, manifest_hash=? WHERE run_id=?",
            (utcnow(), manifest_hash, run_id),
        )
        self.conn.commit()

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
