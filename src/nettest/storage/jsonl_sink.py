"""Bus consumer that appends Results to daily JSONL files.

The daily filename is derived from `Result.ts` (UTC), so rollover happens
at UTC midnight. Internally consistent with the SQLite `ts` column.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from io import TextIOWrapper
from pathlib import Path

from nettest.bus import ResultBus

log = logging.getLogger(__name__)


class JsonlSink:
    def __init__(self, bus: ResultBus, data_dir: Path, flush_interval_ms: int = 100):
        self._dir = data_dir
        self._flush_interval_s = flush_interval_ms / 1000
        self._queue = bus.subscribe("jsonl", drop_policy="never", max_depth=10_000)
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        current_date: str | None = None
        fp: TextIOWrapper | None = None
        loop = asyncio.get_running_loop()
        last_flush = loop.time()
        try:
            while not self._stopping.is_set() or not self._queue.empty():
                timeout = max(0.0, self._flush_interval_s - (loop.time() - last_flush))
                try:
                    res = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except TimeoutError:
                    if fp:
                        fp.flush()
                        last_flush = loop.time()
                    continue
                date_str = res.ts.strftime("%Y-%m-%d")
                if date_str != current_date or fp is None:
                    if fp:
                        fp.flush()
                        fp.close()
                    fp = (self._dir / f"{date_str}.jsonl").open("a", encoding="utf-8")
                    current_date = date_str
                fp.write(json.dumps(res.to_json_dict(), separators=(",", ":")) + "\n")
        finally:
            if fp:
                with contextlib.suppress(OSError):
                    fp.flush()
                    fp.close()
