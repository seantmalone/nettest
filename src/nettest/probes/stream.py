"""Sustained-download probe — measures throughput and detects mid-stream stalls."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx

from nettest import __version__
from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target

# Identifiable UA. Default httpx UA ("python-httpx/X.Y") is rate-limited
# by Cloudflare and a handful of other speed-test CDNs.
_UA = f"nettest/{__version__} (+https://github.com/seantmalone/nettest)"
_HEADERS = {"User-Agent": _UA}


class StreamProbe(Probe):
    name = "stream"

    def __init__(self, ctx: ProbeContext, stall_threshold_ms: int = 200):
        super().__init__(ctx)
        self.stall_threshold_s = stall_threshold_ms / 1000

    async def measure(self, target: Target) -> Result:
        if target.kind != "stream":
            raise ValueError("stream requires Target(kind='stream')")
        url = target.host
        duration_s = float(target.extra.get("duration_s", 60))

        ts = datetime.now(UTC)
        timeout = httpx.Timeout(self.ctx.timeout_ms / 1000, read=duration_s + 5)
        bytes_total = 0
        stalls: list[float] = []
        t0 = time.perf_counter()
        try:
            last_chunk = t0
            async with (
                httpx.AsyncClient(timeout=timeout, headers=_HEADERS) as client,
                client.stream("GET", url) as resp,
            ):
                if resp.status_code != 200:
                    return Result(
                        ts=ts, host=self.ctx.hostname, probe=self.name,
                        target=target.label(), ok=False,
                        duration_ms=(time.perf_counter() - t0) * 1000,
                        error=f"HTTP {resp.status_code}",
                    )
                async for chunk in resp.aiter_bytes():
                    now = time.perf_counter()
                    gap = now - last_chunk
                    if gap >= self.stall_threshold_s:
                        stalls.append(round(gap * 1000, 1))
                    last_chunk = now
                    bytes_total += len(chunk)
                    if now - t0 >= duration_s:
                        break
            elapsed_s = max(time.perf_counter() - t0, 1e-6)
        except httpx.HTTPError as e:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )

        throughput_mbps = (bytes_total * 8) / elapsed_s / 1_000_000
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=bytes_total > 0,
            duration_ms=elapsed_s * 1000,
            metrics={
                "bytes": bytes_total,
                "throughput_mbps": round(throughput_mbps, 3),
                "stalls": stalls,
                "stall_count": len(stalls),
            },
        )
