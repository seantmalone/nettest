import asyncio

import httpx
import respx

from nettest.probes.bandwidth import BandwidthProbe
from nettest.probes.base import ProbeContext
from nettest.types import Target


@respx.mock
async def test_bandwidth_returns_mbps_and_bytes():
    payload = b"x" * 1_000_000
    respx.get("https://example.com/10mb").mock(
        return_value=httpx.Response(200, content=payload)
    )
    ctx = ProbeContext(hostname="h", interval_ms=300000, timeout_ms=30000)
    probe = BandwidthProbe(ctx)
    res = await probe.run(
        Target(kind="url", host="https://example.com/10mb"), cancel=asyncio.Event(),
    )
    assert res.ok is True
    assert res.metrics["bytes"] == 1_000_000
    assert res.metrics["throughput_mbps"] > 0
