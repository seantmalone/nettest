"""Bandwidth snapshot probe — small/medium download with throughput."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx

from nettest import __version__
from nettest.probes.base import Probe
from nettest.types import Result, Target

_UA = f"nettest/{__version__} (+https://github.com/seantmalone/nettest)"
_HEADERS = {"User-Agent": _UA}


class BandwidthProbe(Probe):
    name = "bandwidth"

    async def measure(self, target: Target) -> Result:
        if target.kind != "url":
            raise ValueError("bandwidth requires Target(kind='url')")
        ts = datetime.now(UTC)
        t0 = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=self.ctx.timeout_ms / 1000, headers=_HEADERS,
        ) as client:
            try:
                resp = await client.get(target.host)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error=f"{type(e).__name__}: {e}",
                )
        elapsed_s = max(time.perf_counter() - t0, 1e-6)
        bytes_total = len(resp.content)
        mbps = (bytes_total * 8) / elapsed_s / 1_000_000
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=True,
            duration_ms=elapsed_s * 1000,
            metrics={"bytes": bytes_total, "throughput_mbps": round(mbps, 3)},
        )
