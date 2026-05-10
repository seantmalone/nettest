import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from nettest.storage.background import StorageMaintenance
from nettest.storage.schema import init_schema


async def test_maintenance_runs_rollup_and_retention(tmp_path: Path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    base = int(datetime(2026, 5, 10, 18, 0, tzinfo=UTC).timestamp() * 1000)
    for i in range(60):
        conn.execute(
            "INSERT INTO results (ts, probe, target, ok, duration_ms) "
            "VALUES (?, 'ping', 'x', 1, 1.0)",
            (base + i * 1000,),
        )
    conn.commit()
    conn.close()

    m = StorageMaintenance(
        db_path=db,
        rollup_interval_ms=30,
        retention_interval_ms=30,
        retain_raw_days=7,
        retain_1m_days=90,
        retain_1h_days=365,
        now=lambda: base + 60_000 + 30_000,
    )
    task = asyncio.create_task(m.run())
    await asyncio.sleep(0.1)
    m.stop()
    await task

    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM rollups_1m").fetchone()[0]
    assert n >= 1
    conn.close()
