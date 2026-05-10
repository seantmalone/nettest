"""Compute per-minute and per-hour rollups."""
from __future__ import annotations

import sqlite3

MS_PER_MIN = 60_000
MS_PER_HOUR = 3_600_000


def latest_rollup_bucket(conn: sqlite3.Connection, table: str) -> int | None:
    row = conn.execute(f"SELECT MAX(ts_bucket) FROM {table}").fetchone()  # noqa: S608
    return row[0] if row and row[0] is not None else None


def compute_rollups_1m(conn: sqlite3.Connection, since_ms: int, now_ms: int) -> None:
    bucket_start = (since_ms // MS_PER_MIN) * MS_PER_MIN
    bucket_end = (now_ms // MS_PER_MIN) * MS_PER_MIN
    if bucket_end <= bucket_start:
        return
    rows = conn.execute(
        """
        SELECT
            (ts / ?) * ? AS bucket, probe, target,
            COUNT(*) AS cnt,
            SUM(ok) AS ok_count,
            (1.0 - SUM(ok) * 1.0 / COUNT(*)) * 100.0 AS loss_pct,
            MIN(duration_ms), MAX(duration_ms)
        FROM results
        WHERE ts >= ? AND ts < ?
        GROUP BY bucket, probe, target
        """,
        (MS_PER_MIN, MS_PER_MIN, bucket_start, bucket_end),
    ).fetchall()

    enriched = []
    for bucket, probe, target, cnt, ok_count, loss_pct, _min_ms, max_ms in rows:
        durations = [
            r[0] for r in conn.execute(
                "SELECT duration_ms FROM results WHERE ts >= ? AND ts < ? "
                "AND probe = ? AND target = ? AND duration_ms IS NOT NULL "
                "ORDER BY duration_ms",
                (bucket, bucket + MS_PER_MIN, probe, target),
            )
        ]
        p50 = _percentile(durations, 50)
        p95 = _percentile(durations, 95)
        p99 = _percentile(durations, 99)
        enriched.append(
            (bucket, probe, target, cnt, ok_count, loss_pct, p50, p95, p99, max_ms),
        )

    conn.execute("BEGIN")
    conn.executemany(
        "INSERT OR REPLACE INTO rollups_1m "
        "(ts_bucket, probe, target, count, ok_count, loss_pct, "
        "p50_ms, p95_ms, p99_ms, max_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        enriched,
    )
    conn.execute("COMMIT")


def compute_rollups_1h(conn: sqlite3.Connection, since_ms: int, now_ms: int) -> None:
    bucket_start = (since_ms // MS_PER_HOUR) * MS_PER_HOUR
    bucket_end = (now_ms // MS_PER_HOUR) * MS_PER_HOUR
    if bucket_end <= bucket_start:
        return
    conn.execute("BEGIN")
    conn.execute(
        """
        INSERT OR REPLACE INTO rollups_1h
        (ts_bucket, probe, target, count, ok_count, loss_pct,
         p50_ms, p95_ms, p99_ms, max_ms)
        SELECT
            (ts_bucket / ?) * ? AS hbucket, probe, target,
            SUM(count), SUM(ok_count),
            (1.0 - SUM(ok_count) * 1.0 / SUM(count)) * 100.0 AS loss_pct,
            MAX(p50_ms), MAX(p95_ms), MAX(p99_ms), MAX(max_ms)
        FROM rollups_1m
        WHERE ts_bucket >= ? AND ts_bucket < ?
        GROUP BY hbucket, probe, target
        """,
        (MS_PER_HOUR, MS_PER_HOUR, bucket_start, bucket_end),
    )
    conn.execute("COMMIT")


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
