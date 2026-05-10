import sqlite3
from pathlib import Path

from nettest.storage.schema import init_schema


def test_init_schema_creates_all_tables(tmp_path: Path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur]
    assert {"results", "events", "rollups_1m", "rollups_1h"}.issubset(tables)


def test_init_schema_creates_indexes(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    idx = {r[0] for r in cur}
    assert "idx_results_ts" in idx
    assert "idx_results_probe_tgt_ts" in idx
    assert "idx_events_ts" in idx


def test_init_schema_is_idempotent(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    init_schema(conn)  # second call must not raise
