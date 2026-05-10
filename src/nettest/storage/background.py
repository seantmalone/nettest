"""Periodic rollup + retention maintenance loop."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from nettest.storage.retention import prune_results, prune_rollups_1h, prune_rollups_1m
from nettest.storage.rollups import compute_rollups_1h, compute_rollups_1m

log = logging.getLogger(__name__)


class StorageMaintenance:
    def __init__(
        self,
        db_path: Path,
        rollup_interval_ms: int = 60_000,
        retention_interval_ms: int = 3_600_000,
        retain_raw_days: int = 7,
        retain_1m_days: int = 90,
        retain_1h_days: int = 365,
        now: Callable[[], int] | None = None,
    ):
        self._db_path = db_path
        self._rollup_s = rollup_interval_ms / 1000
        self._retention_s = retention_interval_ms / 1000
        self._raw_d = retain_raw_days
        self._d1m = retain_1m_days
        self._d1h = retain_1h_days
        self._now = now or (lambda: int(time.time() * 1000))
        self._stopping = asyncio.Event()
        self._last_rollup_ms = 0
        self._last_retention_ms = 0

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception:
                log.exception("storage maintenance tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=min(self._rollup_s, self._retention_s),
                )

    async def _tick(self) -> None:
        now_ms = self._now()
        conn = sqlite3.connect(self._db_path)
        try:
            since_1m = self._last_rollup_ms or (now_ms - 24 * 3600 * 1000)
            compute_rollups_1m(conn, since_ms=since_1m, now_ms=now_ms)
            compute_rollups_1h(conn, since_ms=since_1m, now_ms=now_ms)
            self._last_rollup_ms = now_ms
            if (now_ms - self._last_retention_ms) >= self._retention_s * 1000:
                prune_results(conn, now_ms=now_ms, retain_days=self._raw_d)
                prune_rollups_1m(conn, now_ms=now_ms, retain_days=self._d1m)
                prune_rollups_1h(conn, now_ms=now_ms, retain_days=self._d1h)
                self._last_retention_ms = now_ms
        finally:
            conn.close()
