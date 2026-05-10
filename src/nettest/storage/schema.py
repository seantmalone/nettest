"""SQLite schema initialization."""
from __future__ import annotations

import sqlite3

DDL = [
    """CREATE TABLE IF NOT EXISTS results (
        id          INTEGER PRIMARY KEY,
        ts          INTEGER NOT NULL,
        probe       TEXT NOT NULL,
        target      TEXT NOT NULL,
        ok          INTEGER NOT NULL,
        duration_ms REAL,
        error       TEXT,
        metrics     TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_results_ts ON results(ts)",
    "CREATE INDEX IF NOT EXISTS idx_results_probe_tgt_ts ON results(probe, target, ts)",
    """CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY,
        ts_start    INTEGER NOT NULL,
        ts_end      INTEGER NOT NULL,
        kind        TEXT NOT NULL,
        severity    TEXT NOT NULL,
        summary     TEXT NOT NULL,
        details     TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_start)",
    """CREATE TABLE IF NOT EXISTS rollups_1m (
        ts_bucket   INTEGER NOT NULL,
        probe       TEXT NOT NULL,
        target      TEXT NOT NULL,
        count       INTEGER NOT NULL,
        ok_count    INTEGER NOT NULL,
        loss_pct    REAL NOT NULL,
        p50_ms      REAL,
        p95_ms      REAL,
        p99_ms      REAL,
        max_ms      REAL,
        PRIMARY KEY (ts_bucket, probe, target)
    )""",
    """CREATE TABLE IF NOT EXISTS rollups_1h (
        ts_bucket   INTEGER NOT NULL,
        probe       TEXT NOT NULL,
        target      TEXT NOT NULL,
        count       INTEGER NOT NULL,
        ok_count    INTEGER NOT NULL,
        loss_pct    REAL NOT NULL,
        p50_ms      REAL,
        p95_ms      REAL,
        p99_ms      REAL,
        max_ms      REAL,
        PRIMARY KEY (ts_bucket, probe, target)
    )""",
]

PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=134217728",
]


def init_schema(conn: sqlite3.Connection) -> None:
    for p in PRAGMAS:
        conn.execute(p)
    for stmt in DDL:
        conn.execute(stmt)
    conn.commit()
