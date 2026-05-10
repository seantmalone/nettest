import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from nettest.storage.schema import init_schema
from nettest.web.app import build_app


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "x.db"
    conn = sqlite3.connect(p)
    init_schema(conn)
    base = 1_715_366_400_000
    for i in range(20):
        conn.execute(
            "INSERT INTO results (ts, probe, target, ok, duration_ms) "
            "VALUES (?, 'ping', 'x', 1, ?)",
            (base + i * 250, float(i)),
        )
    conn.execute(
        "INSERT INTO events (ts_start, ts_end, kind, severity, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (base, base + 100, "k", "info", "s"),
    )
    conn.commit()
    conn.close()
    return p


async def test_status_endpoint_returns_snapshot(db: Path):
    app = build_app(db_path=db, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/api/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_results_endpoint_filters_by_probe(db: Path):
    app = build_app(db_path=db, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/api/results", params={
            "probe": "ping", "target": "x",
            "from": 1_715_366_400_000, "to": 1_715_366_410_000,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all(r["probe"] == "ping" for r in body)


async def test_events_endpoint_returns_events(db: Path):
    app = build_app(db_path=db, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/api/events", params={
            "from": 0, "to": 9_999_999_999_999,
        })
    assert resp.status_code == 200
    assert resp.json()[0]["kind"] == "k"


async def test_index_page_served(db: Path):
    app = build_app(db_path=db, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


async def test_csv_export_escapes_commas_in_error(tmp_path: Path):
    p = tmp_path / "x.db"
    conn = sqlite3.connect(p)
    init_schema(conn)
    base = 1_715_366_400_000
    conn.execute(
        "INSERT INTO results (ts, probe, target, ok, duration_ms, error) "
        "VALUES (?, 'http', 'x', 0, 1.0, ?)",
        (base, "connection refused, port 443"),
    )
    conn.commit()
    conn.close()
    app = build_app(db_path=p, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get(
            "/api/export.csv",
            params={"from": 0, "to": 9_999_999_999_999},
        )
    assert resp.status_code == 200
    assert '"connection refused, port 443"' in resp.text


async def test_ws_live_streams_events_when_broadcaster_provided(db: Path):
    """Smoke test that build_app accepts an events broadcaster."""
    from nettest.bus import ResultBus
    from nettest.tui.event_broadcast import EventBroadcast
    bus = ResultBus()
    eb = EventBroadcast()
    app = build_app(db_path=db, hostname="h", bus=bus, events=eb)
    # If construction succeeds and /ws/live is registered, we're good
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/ws/live" in routes


async def test_results_endpoint_uses_rollups_for_long_range(tmp_path: Path):
    p = tmp_path / "x.db"
    conn = sqlite3.connect(p)
    init_schema(conn)
    base = 1_715_366_400_000
    for i in range(5):
        conn.execute(
            "INSERT INTO rollups_1m "
            "(ts_bucket, probe, target, count, ok_count, loss_pct, "
            "p50_ms, p95_ms, p99_ms, max_ms) "
            "VALUES (?, 'ping', 'x', 60, 60, 0.0, 1.0, 2.0, 3.0, 4.0)",
            (base + i * 60_000,),
        )
    conn.commit()
    conn.close()
    app = build_app(db_path=p, hostname="h")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/api/results", params={
            "probe": "ping", "target": "x",
            "from": base, "to": base + 6 * 3_600_000,
        })
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 5
    assert "p95_ms" in rows[0]
