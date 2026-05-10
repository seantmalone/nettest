import sqlite3
from datetime import UTC, datetime

from nettest.storage.schema import init_schema
from nettest.web.queries import (
    pick_resolution,
    query_events,
    query_results,
    query_rollups_1h,
    query_rollups_1m,
)


def _ms(d: datetime) -> int:
    return int(d.timestamp() * 1000)


def test_pick_resolution_under_one_hour_returns_raw():
    assert pick_resolution(span_ms=30 * 60_000) == "raw"


def test_pick_resolution_24h_returns_1m():
    assert pick_resolution(span_ms=24 * 3_600_000) == "1m"


def test_pick_resolution_7d_returns_1h():
    assert pick_resolution(span_ms=7 * 24 * 3_600_000) == "1h"


def test_query_results_returns_window():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    base = _ms(datetime(2026, 5, 10, 18, 0, tzinfo=UTC))
    for i in range(10):
        conn.execute(
            "INSERT INTO results (ts, probe, target, ok, duration_ms) "
            "VALUES (?, 'ping', 'x', 1, ?)",
            (base + i * 1000, float(i)),
        )
    conn.commit()
    rows = query_results(conn, probe="ping", target="x", from_ms=base, to_ms=base + 5000)
    assert len(rows) == 6


def test_query_events_filters_by_range():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO events (ts_start, ts_end, kind, severity, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (1000, 1500, "x", "info", "s1"),
    )
    conn.execute(
        "INSERT INTO events (ts_start, ts_end, kind, severity, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (5000, 5500, "y", "warn", "s2"),
    )
    conn.commit()
    rows = query_events(conn, from_ms=2000, to_ms=10000)
    assert len(rows) == 1
    assert rows[0]["kind"] == "y"


def test_query_rollups_1m_returns_buckets():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    base = 1_715_000_000_000
    for i in range(3):
        conn.execute(
            "INSERT INTO rollups_1m "
            "(ts_bucket, probe, target, count, ok_count, loss_pct, "
            "p50_ms, p95_ms, p99_ms, max_ms) "
            "VALUES (?, 'ping', 'x', 60, 59, 1.67, 1.0, 2.0, 3.0, 4.0)",
            (base + i * 60_000,),
        )
    conn.commit()
    rows = query_rollups_1m(conn, "ping", "x", base, base + 3 * 60_000)
    assert len(rows) == 3
    assert rows[0]["p95_ms"] == 2.0


def test_query_rollups_1h_filters_by_probe():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    base = 1_715_000_000_000
    conn.execute(
        "INSERT INTO rollups_1h "
        "(ts_bucket, probe, target, count, ok_count, loss_pct, "
        "p50_ms, p95_ms, p99_ms, max_ms) "
        "VALUES (?, 'ping', 'x', 3600, 3600, 0.0, 1.0, 2.0, 3.0, 4.0)",
        (base,),
    )
    conn.execute(
        "INSERT INTO rollups_1h "
        "(ts_bucket, probe, target, count, ok_count, loss_pct, "
        "p50_ms, p95_ms, p99_ms, max_ms) "
        "VALUES (?, 'http', 'y', 3600, 3600, 0.0, 1.0, 2.0, 3.0, 4.0)",
        (base,),
    )
    conn.commit()
    rows = query_rollups_1h(conn, "ping", None, base, base + 1)
    assert len(rows) == 1
    assert rows[0]["probe"] == "ping"
