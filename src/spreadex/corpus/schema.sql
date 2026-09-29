-- SpreadEx corpus. SQLite holds metadata; input bytes live in blobs/ addressed
-- by SHA-256, so the same program produced by two generators, or reappearing in
-- a later SUT version, is stored once and its whole history joins for free.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS inputs (
    blob_hash       TEXT PRIMARY KEY,       -- sha256 of the input bytes
    generator       TEXT NOT NULL,
    grammar_version TEXT,
    generated_at    TEXT NOT NULL,
    valid           INTEGER,                -- NULL = not yet validated
    gen_cost_ms     REAL,
    size_bytes      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_inputs_generator ON inputs(generator);

-- The same input may come from several generators; keep every attribution.
CREATE TABLE IF NOT EXISTS input_origins (
    blob_hash    TEXT NOT NULL REFERENCES inputs(blob_hash) ON DELETE CASCADE,
    generator    TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (blob_hash, generator)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    config_hash   TEXT NOT NULL,
    manifest_hash TEXT,
    seed          INTEGER,
    gen_budget_s  REAL,
    exec_budget_s REAL,
    signal_name   TEXT,                     -- which SelectionSignal ordered the corpus
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    blob_hash    TEXT NOT NULL REFERENCES inputs(blob_hash) ON DELETE CASCADE,
    rank         INTEGER NOT NULL,          -- position in the prioritized order
    sut_id       TEXT NOT NULL,
    sut_version  TEXT,
    exit_code    INTEGER,
    signal       INTEGER,
    timed_out    INTEGER NOT NULL DEFAULT 0,
    duration_ms  REAL,
    stdout_hash  TEXT,
    stderr_hash  TEXT,
    verdict      TEXT,                      -- ok | expected_rejection | crash | timeout | divergence
    signature    TEXT,
    detail       TEXT,
    PRIMARY KEY (run_id, blob_hash, sut_id)
);
CREATE INDEX IF NOT EXISTS idx_exec_verdict   ON executions(verdict);
CREATE INDEX IF NOT EXISTS idx_exec_signature ON executions(signature);
CREATE INDEX IF NOT EXISTS idx_exec_blob      ON executions(blob_hash);

CREATE TABLE IF NOT EXISTS failures (
    signature           TEXT PRIMARY KEY,
    verdict             TEXT NOT NULL,
    first_seen_run      TEXT REFERENCES runs(run_id),
    first_seen_at       TEXT NOT NULL,
    last_seen_run       TEXT REFERENCES runs(run_id),
    occurrences         INTEGER NOT NULL DEFAULT 1,
    example_blob_hash   TEXT REFERENCES inputs(blob_hash),
    minimized_blob_hash TEXT REFERENCES inputs(blob_hash),
    detail              TEXT
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
