"""Insert Events into the events table."""
from __future__ import annotations

import sqlite3

from nettest.events import Event


def insert_event(conn: sqlite3.Connection, event: Event) -> int:
    cur = conn.execute(
        "INSERT INTO events (ts_start, ts_end, kind, severity, summary, details) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        event.to_row(),
    )
    conn.commit()
    return cur.lastrowid or 0
