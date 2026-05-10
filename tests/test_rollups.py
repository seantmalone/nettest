import sqlite3
from pathlib import Path

from nettest.storage.rollups import (
    compute_rollups_1h,
    compute_rollups_1m,
    latest_rollup_bucket,
)
from nettest.storage.schema import init_schema


def _seed(
    conn: sqlite3.Connection,
    ts_ms: int,
    probe: str,
    target: str,
    ok: int,
    ms: float,
):
    conn.execute(
        "INSERT INTO results (ts, probe, target, ok, duration_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        (ts_ms, probe, target, ok, ms),
    )


def test_rollup_1m_aggregates_per_minute(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    base = 1_715_366_400_000
    for i in range(60):
        _seed(conn, base + i * 1000, "ping", "1.1.1.1", 1, 10 + i)
    for i in range(5):
        _seed(conn, base + i * 1000, "ping", "1.1.1.1", 0, 0)
    conn.commit()

    compute_rollups_1m(conn, since_ms=base, now_ms=base + 60_000)

    row = conn.execute(
        "SELECT count, ok_count, loss_pct, p50_ms, p95_ms FROM rollups_1m"
    ).fetchone()
    assert row[0] == 65
    assert row[1] == 60
    assert abs(row[2] - (5 / 65 * 100)) < 0.001
    assert row[3] is not None
    assert row[4] is not None


def test_rollup_1h_aggregates_from_1m(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    hour_start = 1_715_366_400_000
    for m in range(60):
        conn.execute(
            "INSERT INTO rollups_1m "
            "(ts_bucket, probe, target, count, ok_count, loss_pct, "
            "p50_ms, p95_ms, p99_ms, max_ms) "
            "VALUES (?, 'ping', '1.1.1.1', ?, ?, ?, ?, ?, ?, ?)",
            (hour_start + m * 60_000, 100, 99, 1.0, 10.0, 20.0, 30.0, 40.0),
        )
    conn.commit()

    compute_rollups_1h(conn, since_ms=hour_start, now_ms=hour_start + 3_600_000)

    row = conn.execute("SELECT count, ok_count, loss_pct FROM rollups_1h").fetchone()
    assert row[0] == 6000
    assert row[1] == 5940
    assert abs(row[2] - 1.0) < 0.001


def test_latest_rollup_bucket_returns_none_when_empty():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    assert latest_rollup_bucket(conn, "rollups_1m") is None
