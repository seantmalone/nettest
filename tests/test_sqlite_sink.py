import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from nettest.bus import ResultBus
from nettest.storage.schema import init_schema
from nettest.storage.sqlite_sink import SqliteSink
from nettest.types import Result


def make_result(ok: bool = True) -> Result:
    return Result(
        ts=datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC),
        host="h", probe="ping", target="1.1.1.1",
        ok=ok, duration_ms=14.2,
        metrics={"foo": 1},
    )


async def test_sqlite_sink_writes_batched(tmp_path: Path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.close()

    bus = ResultBus()
    sink = SqliteSink(bus=bus, db_path=db, batch_size=3, flush_interval_ms=50)
    task = asyncio.create_task(sink.run())

    for _ in range(5):
        await bus.publish(make_result())
    await asyncio.sleep(0.15)
    sink.stop()
    await task

    conn = sqlite3.connect(db)
    rows = list(conn.execute("SELECT probe, target, ok, metrics FROM results"))
    assert len(rows) == 5
    assert json.loads(rows[0][3]) == {"foo": 1}
    conn.close()


async def test_sqlite_sink_does_not_wedge_after_idle(tmp_path: Path):
    """Regression: an idle gap >= flush_interval before the first result
    used to pin the wait_for timeout at 0.0 forever, so the queue was
    never drained and nothing persisted. Results published after the
    idle period must still be written while the sink is running.
    """
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.close()

    bus = ResultBus()
    sink = SqliteSink(bus=bus, db_path=db, batch_size=3, flush_interval_ms=50)
    task = asyncio.create_task(sink.run())

    # Idle well past the 50ms flush interval before any result arrives.
    await asyncio.sleep(0.3)
    for _ in range(4):
        await bus.publish(make_result())
    await asyncio.sleep(0.3)

    # Assert BEFORE stop() so the final-flush path can't mask a wedge.
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    conn.close()
    sink.stop()
    await task
    assert count == 4


async def test_sqlite_sink_handles_failure_results(tmp_path: Path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.close()
    bus = ResultBus()
    sink = SqliteSink(bus=bus, db_path=db, batch_size=1, flush_interval_ms=10)
    task = asyncio.create_task(sink.run())

    await bus.publish(make_result(ok=False))
    await asyncio.sleep(0.05)
    sink.stop()
    await task

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT ok FROM results").fetchone()
    assert row[0] == 0
    conn.close()
