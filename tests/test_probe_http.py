import asyncio

import httpx
import respx

from nettest.probes.base import ProbeContext
from nettest.probes.http import HttpProbe
from nettest.types import Target


@respx.mock
async def test_http_probe_records_full_timing_breakdown():
    respx.get("https://example.com/").mock(
        return_value=httpx.Response(200, content=b"hello world")
    )
    ctx = ProbeContext(hostname="h", interval_ms=2000, timeout_ms=5000)
    probe = HttpProbe(ctx)
    res = await probe.run(
        Target(kind="url", host="https://example.com/"), cancel=asyncio.Event(),
    )
    assert res.ok is True
    assert res.metrics["status"] == 200
    assert res.metrics["size_bytes"] == len(b"hello world")
    for key in ("dns_ms", "connect_ms", "tls_ms", "ttfb_ms"):
        assert key in res.metrics, f"metrics missing {key}"
    assert res.duration_ms > 0


@respx.mock
async def test_http_probe_5xx_is_failure():
    respx.get("https://example.com/x").mock(return_value=httpx.Response(503))
    ctx = ProbeContext(hostname="h", interval_ms=2000, timeout_ms=5000)
    probe = HttpProbe(ctx)
    res = await probe.run(
        Target(kind="url", host="https://example.com/x"), cancel=asyncio.Event(),
    )
    assert res.ok is False
    assert res.error == "HTTP 503"


@respx.mock
async def test_http_probe_network_error_is_failure():
    respx.get("https://example.com/y").mock(side_effect=httpx.ConnectError("refused"))
    ctx = ProbeContext(hostname="h", interval_ms=2000, timeout_ms=5000)
    probe = HttpProbe(ctx)
    res = await probe.run(
        Target(kind="url", host="https://example.com/y"), cancel=asyncio.Event(),
    )
    assert res.ok is False
    assert "refused" in (res.error or "")
