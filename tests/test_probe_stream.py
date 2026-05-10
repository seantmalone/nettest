import asyncio

import httpx
import respx

from nettest.probes.base import ProbeContext
from nettest.probes.stream import StreamProbe
from nettest.types import Target


@respx.mock
async def test_stream_probe_records_bytes_and_throughput():
    payload = b"x" * 100_000
    respx.get("https://example.com/stream").mock(
        return_value=httpx.Response(200, content=payload)
    )
    ctx = ProbeContext(hostname="h", interval_ms=60000, timeout_ms=5000)
    probe = StreamProbe(ctx, stall_threshold_ms=200)
    res = await probe.run(
        Target(kind="stream", host="https://example.com/stream", extra={"duration_s": 1}),
        cancel=asyncio.Event(),
    )
    assert res.ok is True
    assert res.metrics["bytes"] == len(payload)
    assert res.metrics["throughput_mbps"] >= 0
    assert isinstance(res.metrics["stalls"], list)
