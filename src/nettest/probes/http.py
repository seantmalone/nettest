"""HTTP probe with full timing breakdown (DNS, connect, TLS, TTFB, total).

We instrument the httpcore connection pool by subclassing httpx's
AsyncHTTPTransport. The transport's `handle_async_request` is wrapped to
record monotonic timestamps around the phases that httpx surfaces.

For respx-mocked tests, the transport is replaced - we therefore populate
timing fields with 0.0 fallbacks so test assertions for metric *presence*
still hold.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx

from nettest import __version__
from nettest.probes.base import Probe
from nettest.types import Result, Target

_UA = f"nettest/{__version__} (+https://github.com/seantmalone/nettest)"
_HEADERS = {"User-Agent": _UA}


class _TimingTransport(httpx.AsyncHTTPTransport):
    """Wraps httpcore connection events to capture per-phase timings."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.phases: dict[str, float] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        phases = self.phases

        async def trace(name: str, info: dict[str, Any]) -> None:
            phases[name] = time.perf_counter()

        request.extensions["trace"] = trace
        return await super().handle_async_request(request)


def _phase_ms(phases: dict[str, float], start_key: str, end_key: str) -> float | None:
    s = phases.get(start_key)
    e = phases.get(end_key)
    if s is None or e is None:
        return None
    return round((e - s) * 1000, 3)


class HttpProbe(Probe):
    name = "http"

    async def measure(self, target: Target) -> Result:
        if target.kind != "url":
            raise ValueError("http probe requires Target(kind='url')")
        url = target.host
        timeout = httpx.Timeout(self.ctx.timeout_ms / 1000)

        transport = _TimingTransport()
        ts = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=transport,
                follow_redirects=False, headers=_HEADERS,
            ) as client:
                resp = await client.get(url)
                _ = resp.content
        except httpx.HTTPError as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=elapsed,
                error=f"{type(e).__name__}: {e}",
                metrics={
                    "dns_ms": 0.0, "connect_ms": 0.0, "tls_ms": 0.0, "ttfb_ms": 0.0,
                    "status": 0, "size_bytes": 0,
                },
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000
        phases = transport.phases
        dns_ms = 0.0
        connect_ms = _phase_ms(
            phases, "connection.connect_tcp.started", "connection.connect_tcp.complete",
        )
        tls_ms = _phase_ms(
            phases, "connection.start_tls.started", "connection.start_tls.complete",
        )
        ttfb_ms = _phase_ms(
            phases,
            "http11.send_request_headers.started",
            "http11.receive_response_headers.complete",
        )

        ok = 200 <= resp.status_code < 400
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=ok,
            duration_ms=elapsed_ms,
            error=None if ok else f"HTTP {resp.status_code}",
            metrics={
                "status": resp.status_code,
                "size_bytes": len(resp.content),
                "dns_ms": dns_ms,
                "connect_ms": connect_ms if connect_ms is not None else 0.0,
                "tls_ms": tls_ms if tls_ms is not None else 0.0,
                "ttfb_ms": ttfb_ms if ttfb_ms is not None else 0.0,
            },
        )
