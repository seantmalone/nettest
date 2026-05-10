"""Plain TCP connect probe."""
from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import UTC, datetime

from nettest.probes.base import Probe
from nettest.types import Result, Target


class TcpConnectProbe(Probe):
    name = "tcp_connect"

    async def measure(self, target: Target) -> Result:
        if target.kind != "tcp" or target.port is None:
            raise ValueError("tcp_connect requires Target(kind='tcp', port=...)")
        ts = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            _reader, writer = await asyncio.open_connection(target.host, target.port)
        except (ConnectionError, OSError) as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
            )
        elapsed = (time.perf_counter() - t0) * 1000
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=True,
            duration_ms=elapsed,
        )
