"""Path MTU probe — pings with DF set across configured sizes."""
from __future__ import annotations

import asyncio
import platform
import time
from datetime import UTC, datetime

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


class MtuProbe(Probe):
    name = "mtu"

    def __init__(self, ctx: ProbeContext, sizes: list[int] | None = None):
        super().__init__(ctx)
        self.sizes = sorted(sizes or [1500, 1472, 1400, 1200, 1000, 576], reverse=True)

    async def measure(self, target: Target) -> Result:
        ts = datetime.now(UTC)
        t0 = time.perf_counter()
        for size in self.sizes:
            ok = await self._ping_df(target.host, size)
            if ok:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=True,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    metrics={"mtu": size, "tested_sizes": self.sizes},
                )
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=False,
            duration_ms=(time.perf_counter() - t0) * 1000,
            error="all sizes blocked",
            metrics={"tested_sizes": self.sizes},
        )

    async def _ping_df(self, host: str, payload_size: int) -> bool:
        # Probe.run() enforces self.ctx.timeout_ms as the total budget. Divide
        # by (sizes + 2) so the iteration fits AND leaves slack for subprocess
        # startup and Probe.run's own bookkeeping. Without the +2 slack, an
        # all-fail path exactly equals the outer timeout and gets cancelled
        # before returning a clean "all sizes blocked" result.
        per_iter_ms = max(200, self.ctx.timeout_ms // (len(self.sizes) + 2))
        sysname = platform.system()
        if sysname == "Windows":
            cmd = [
                "ping", "-n", "1", "-f", "-l", str(payload_size),
                "-w", str(per_iter_ms), host,
            ]
        elif sysname == "Darwin":
            cmd = [
                "ping", "-c", "1", "-D", "-s", str(payload_size),
                "-W", str(per_iter_ms), host,
            ]
        else:
            cmd = [
                "ping", "-c", "1", "-M", "do", "-s", str(payload_size),
                "-W", str(max(1, per_iter_ms // 1000)), host,
            ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        return rc == 0
