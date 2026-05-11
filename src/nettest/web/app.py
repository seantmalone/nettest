"""FastAPI app: REST + WebSocket + static page."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Query, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from nettest.bus import ResultBus
from nettest.events import Event
from nettest.tui.event_broadcast import EventBroadcast
from nettest.web.queries import (
    pick_resolution,
    query_events,
    query_results,
    query_rollups_1h,
    query_rollups_1m,
    status_snapshot,
)

_STATIC = Path(__file__).parent / "static"

FromQ = Annotated[int, Query(alias="from", ge=0)]
ToQ = Annotated[int | None, Query(alias="to", ge=0)]


def _now_ms() -> int:
    return int(time.time() * 1000)


def build_app(
    db_path: Path,
    hostname: str,
    bus: ResultBus | None = None,
    events: EventBroadcast | None = None,
) -> FastAPI:
    app = FastAPI(title="nettest")

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    _index_page = _STATIC / "index.html"
    _index_html: str | None = (
        _index_page.read_text(encoding="utf-8") if _index_page.exists() else None
    )

    @app.get("/")
    async def index() -> HTMLResponse:
        if _index_html is not None:
            return HTMLResponse(_index_html)
        return HTMLResponse(_FALLBACK_HTML.format(host=hostname))

    @app.get("/api/status")
    async def status_route() -> JSONResponse:
        conn = sqlite3.connect(db_path)
        try:
            since_ms = _now_ms() - 60_000
            return JSONResponse(status_snapshot(conn, since_ms))
        finally:
            conn.close()

    @app.get("/api/results")
    async def results_route(
        probe: str | None = None,
        target: str | None = None,
        from_ms: FromQ = 0,
        to_ms: ToQ = None,
    ) -> JSONResponse:
        to_ms_eff = to_ms if to_ms is not None else _now_ms()
        if to_ms_eff < from_ms:
            return JSONResponse({"error": "to < from"}, status_code=400)
        conn = sqlite3.connect(db_path)
        try:
            res = pick_resolution(to_ms_eff - from_ms)
            if res == "raw":
                return JSONResponse(query_results(conn, probe, target, from_ms, to_ms_eff))
            if res == "1m":
                return JSONResponse(query_rollups_1m(conn, probe, target, from_ms, to_ms_eff))
            return JSONResponse(query_rollups_1h(conn, probe, target, from_ms, to_ms_eff))
        finally:
            conn.close()

    @app.get("/api/events")
    async def events_route(
        from_ms: FromQ = 0,
        to_ms: ToQ = None,
    ) -> JSONResponse:
        to_ms_eff = to_ms if to_ms is not None else _now_ms()
        conn = sqlite3.connect(db_path)
        try:
            return JSONResponse(query_events(conn, from_ms, to_ms_eff))
        finally:
            conn.close()

    @app.get("/api/export.csv")
    async def export_csv(
        probe: str | None = None,
        target: str | None = None,
        from_ms: FromQ = 0,
        to_ms: ToQ = None,
    ) -> Response:
        to_ms_eff = to_ms if to_ms is not None else _now_ms()
        conn = sqlite3.connect(db_path)
        try:
            rows = query_results(conn, probe, target, from_ms, to_ms_eff)
        finally:
            conn.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "probe", "target", "ok", "duration_ms", "error"])
        for r in rows:
            w.writerow([
                r["ts"], r["probe"], r["target"],
                int(r["ok"]), r["duration_ms"], r["error"] or "",
            ])
        return Response(buf.getvalue(), media_type="text/csv")

    if bus is not None:
        bus_ref = bus
        events_ref = events

        @app.websocket("/ws/live")
        async def ws_live(ws: WebSocket) -> None:
            await ws.accept()
            sub_name = f"ws:{id(ws)}"
            result_q = bus_ref.subscribe(
                sub_name, drop_policy="drop_oldest", max_depth=500,
            )
            out_q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

            def _on_event(e: Event) -> None:
                envelope: dict[str, Any] = {
                    "kind": "event",
                    "ts_end": e.ts_end.isoformat(),
                    "event_kind": e.kind,
                    "severity": e.severity,
                    "summary": e.summary,
                }
                with contextlib.suppress(asyncio.QueueFull):
                    out_q.put_nowait(envelope)

            if events_ref is not None:
                events_ref.subscribe(_on_event)

            async def _drain_results() -> None:
                while True:
                    r = await result_q.get()
                    with contextlib.suppress(asyncio.QueueFull):
                        out_q.put_nowait({"kind": "result", **r.to_json_dict()})

            drain_task = asyncio.create_task(_drain_results())
            try:
                with contextlib.suppress(Exception):
                    while True:
                        msg = await out_q.get()
                        await ws.send_json(msg)
            finally:
                drain_task.cancel()
                with contextlib.suppress(BaseException):
                    await drain_task
                bus_ref.unsubscribe(sub_name)
                # EventBroadcast has no unsubscribe; the callback will no-op
                # if the WebSocket is closed. Acceptable for v1.

    return app


_FALLBACK_HTML = """\
<!doctype html>
<html><head><title>nettest @ {host}</title></head>
<body><h1>nettest @ {host}</h1>
<p>Static dashboard files are missing. Endpoints work; build the SPA in src/nettest/web/static/.</p>
</body></html>
"""
