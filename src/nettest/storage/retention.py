"""Prune old data, respecting the rollup-before-retention invariant."""
from __future__ import annotations

import sqlite3

from nettest.storage.rollups import latest_rollup_bucket


def prune_results(conn: sqlite3.Connection, now_ms: int, retain_days: int) -> int:
    floor = latest_rollup_bucket(conn, "rollups_1m")
    if floor is None:
        return 0
    target_cutoff = now_ms - retain_days * 24 * 3600 * 1000
    effective = min(target_cutoff, floor)
    cur = conn.execute("DELETE FROM results WHERE ts < ?", (effective,))
    conn.commit()
    return cur.rowcount


def prune_rollups_1m(conn: sqlite3.Connection, now_ms: int, retain_days: int) -> int:
    cutoff = now_ms - retain_days * 24 * 3600 * 1000
    floor = latest_rollup_bucket(conn, "rollups_1h")
    if floor is None:
        return 0
    effective = min(cutoff, floor)
    cur = conn.execute("DELETE FROM rollups_1m WHERE ts_bucket < ?", (effective,))
    conn.commit()
    return cur.rowcount


def prune_rollups_1h(conn: sqlite3.Connection, now_ms: int, retain_days: int) -> int:
    cutoff = now_ms - retain_days * 24 * 3600 * 1000
    cur = conn.execute("DELETE FROM rollups_1h WHERE ts_bucket < ?", (cutoff,))
    conn.commit()
    return cur.rowcount
