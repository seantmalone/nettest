"""Read-side queries for the dashboard API."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

Resolution = Literal["raw", "1m", "1h"]

_HOUR_MS = 3_600_000
_DAY_MS = 24 * _HOUR_MS


def pick_resolution(span_ms: int) -> Resolution:
    if span_ms <= _HOUR_MS:
        return "raw"
    if span_ms <= _DAY_MS:
        return "1m"
    return "1h"


def query_results(
    conn: sqlite3.Connection,
    probe: str | None,
    target: str | None,
    from_ms: int,
    to_ms: int,
    limit: int = 50_000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT ts, probe, target, ok, duration_ms, error, metrics "
        "FROM results WHERE ts >= ? AND ts <= ?"
    )
    params: list[Any] = [from_ms, to_ms]
    if probe:
        sql += " AND probe = ?"
        params.append(probe)
    if target:
        sql += " AND target = ?"
        params.append(target)
    sql += " ORDER BY ts LIMIT ?"
    params.append(limit)
    return [
        {
            "ts": row[0], "probe": row[1], "target": row[2],
            "ok": bool(row[3]), "duration_ms": row[4], "error": row[5],
            "metrics": json.loads(row[6]) if row[6] else None,
        }
        for row in conn.execute(sql, params)
    ]


def query_rollups_1m(
    conn: sqlite3.Connection, probe: str | None, target: str | None,
    from_ms: int, to_ms: int,
) -> list[dict[str, Any]]:
    return _query_rollups(conn, "rollups_1m", probe, target, from_ms, to_ms)


def query_rollups_1h(
    conn: sqlite3.Connection, probe: str | None, target: str | None,
    from_ms: int, to_ms: int,
) -> list[dict[str, Any]]:
    return _query_rollups(conn, "rollups_1h", probe, target, from_ms, to_ms)


def _query_rollups(
    conn: sqlite3.Connection,
    table: str,
    probe: str | None,
    target: str | None,
    from_ms: int,
    to_ms: int,
) -> list[dict[str, Any]]:
    sql = (
        f"SELECT ts_bucket, probe, target, count, ok_count, loss_pct, "
        f"p50_ms, p95_ms, p99_ms, max_ms FROM {table} "  # noqa: S608
        f"WHERE ts_bucket >= ? AND ts_bucket <= ?"
    )
    params: list[Any] = [from_ms, to_ms]
    if probe:
        sql += " AND probe = ?"
        params.append(probe)
    if target:
        sql += " AND target = ?"
        params.append(target)
    sql += " ORDER BY ts_bucket"
    return [
        {
            "ts_bucket": r[0], "probe": r[1], "target": r[2],
            "count": r[3], "ok_count": r[4], "loss_pct": r[5],
            "p50_ms": r[6], "p95_ms": r[7], "p99_ms": r[8], "max_ms": r[9],
        }
        for r in conn.execute(sql, params)
    ]


def query_events(
    conn: sqlite3.Connection, from_ms: int, to_ms: int,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, ts_start, ts_end, kind, severity, summary, details "
        "FROM events WHERE ts_start >= ? AND ts_start <= ? ORDER BY ts_start"
    )
    return [
        {
            "id": r[0], "ts_start": r[1], "ts_end": r[2], "kind": r[3],
            "severity": r[4], "summary": r[5],
            "details": json.loads(r[6]) if r[6] else None,
        }
        for r in conn.execute(sql, (from_ms, to_ms))
    ]


def status_snapshot(
    conn: sqlite3.Connection, since_ms: int,
) -> list[dict[str, Any]]:
    sql = """
        SELECT probe, target, ts, ok, duration_ms, error
        FROM results
        WHERE ts >= ?
        GROUP BY probe, target
        HAVING ts = MAX(ts)
        ORDER BY probe, target
    """
    return [
        {
            "probe": r[0], "target": r[1], "ts": r[2],
            "ok": bool(r[3]), "duration_ms": r[4], "error": r[5],
        }
        for r in conn.execute(sql, (since_ms,))
    ]
