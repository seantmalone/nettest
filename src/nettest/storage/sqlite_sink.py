"""Bus consumer that batches Results into SQLite."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from pathlib import Path

from nettest.bus import ResultBus
from nettest.types import Result

log = logging.getLogger(__name__)


class SqliteSink:
    def __init__(
        self,
        bus: ResultBus,
        db_path: Path,
        batch_size: int = 50,
        flush_interval_ms: int = 100,
    ):
        self._db_path = db_path
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_ms / 1000
        self._queue = bus.subscribe("sqlite", drop_policy="never", max_depth=10_000)
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        try:
            buf: list[Result] = []
            loop = asyncio.get_running_loop()
            last_flush = loop.time()
            while not self._stopping.is_set() or buf or not self._queue.empty():
                # With nothing buffered there's no pending flush deadline.
                # Advancing last_flush here keeps the wait_for timeout at a
                # full interval so queue.get() actually gets polled. Without
                # this, once (now - last_flush) >= flush_interval while the
                # buffer is empty, the timeout pins at 0.0 forever and
                # wait_for(get, 0.0) never dequeues — wedging the sink.
                if not buf:
                    last_flush = loop.time()
                timeout = max(0.0, self._flush_interval_s - (loop.time() - last_flush))
                with contextlib.suppress(TimeoutError):
                    item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                    buf.append(item)
                if len(buf) >= self._batch_size or (
                    buf and (loop.time() - last_flush) >= self._flush_interval_s
                ):
                    self._flush(conn, buf)
                    buf.clear()
                    last_flush = loop.time()
        finally:
            try:
                if buf:
                    self._flush(conn, buf)
            finally:
                conn.close()

    @staticmethod
    def _flush(conn: sqlite3.Connection, batch: list[Result]) -> None:
        rows = [
            (
                int(r.ts.timestamp() * 1000),
                r.probe, r.target,
                1 if r.ok else 0,
                r.duration_ms, r.error,
                json.dumps(r.metrics, separators=(",", ":")) if r.metrics else None,
            )
            for r in batch
        ]
        try:
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT INTO results (ts, probe, target, ok, duration_ms, error, metrics) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            log.exception("sqlite flush failed (%d rows)", len(rows))
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
