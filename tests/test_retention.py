import sqlite3
from datetime import UTC, datetime

from nettest.storage.retention import prune_results
from nettest.storage.schema import init_schema


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1000)


def test_prune_results_respects_rollup_floor():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    for d in range(1, 11):
        conn.execute(
            "INSERT INTO results (ts, probe, target, ok, duration_ms) "
            "VALUES (?, 'ping', 'x', 1, 1.0)",
            (_ms(2026, 5, d),),
        )
    conn.execute(
        "INSERT INTO rollups_1m "
        "(ts_bucket, probe, target, count, ok_count, loss_pct, "
        "p50_ms, p95_ms, p99_ms, max_ms) "
        "VALUES (?, 'ping', 'x', 1, 1, 0.0, 1.0, 1.0, 1.0, 1.0)",
        (_ms(2026, 5, 5),),
    )
    conn.commit()
    now_ms = _ms(2026, 5, 15)

    deleted = prune_results(conn, now_ms=now_ms, retain_days=7)
    remaining = sorted(
        datetime.fromtimestamp(r[0] / 1000, tz=UTC).day
        for r in conn.execute("SELECT ts FROM results")
    )
    assert deleted == 4
    assert remaining == [5, 6, 7, 8, 9, 10]


def test_prune_does_nothing_when_no_rollups():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute(
        "INSERT INTO results (ts, probe, target, ok, duration_ms) "
        "VALUES (?, 'ping', 'x', 1, 1.0)",
        (_ms(2026, 4, 1),),
    )
    conn.commit()
    deleted = prune_results(conn, now_ms=_ms(2026, 5, 15), retain_days=7)
    assert deleted == 0
