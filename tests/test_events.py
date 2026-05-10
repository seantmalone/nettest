import sqlite3
from datetime import UTC, datetime

from nettest.events import Event
from nettest.storage.event_sink import insert_event
from nettest.storage.schema import init_schema


def test_event_to_row():
    e = Event(
        ts_start=datetime(2026, 5, 10, 18, 0, tzinfo=UTC),
        ts_end=datetime(2026, 5, 10, 18, 0, 1, tzinfo=UTC),
        kind="micro_outage",
        severity="warn",
        summary="3 ping fails to 1.1.1.1 in 800ms",
        details={"target": "1.1.1.1", "result_ids": [1, 2, 3]},
    )
    row = e.to_row()
    assert row[2] == "micro_outage"
    assert row[3] == "warn"


def test_insert_event_persists_and_returns_id():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    e = Event(
        ts_start=datetime(2026, 5, 10, 18, 0, tzinfo=UTC),
        ts_end=datetime(2026, 5, 10, 18, 0, 1, tzinfo=UTC),
        kind="x", severity="info", summary="s", details={},
    )
    eid = insert_event(conn, e)
    row = conn.execute(
        "SELECT kind, severity, summary FROM events WHERE id = ?", (eid,),
    ).fetchone()
    assert row == ("x", "info", "s")
