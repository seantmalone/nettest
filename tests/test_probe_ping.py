import asyncio
from unittest.mock import AsyncMock, patch

from nettest.probes.base import ProbeContext
from nettest.probes.ping import PingProbe
from nettest.types import Target


class _FakeIcmpHost:
    def __init__(self, *, is_alive: bool, avg_rtt: float):
        self.is_alive = is_alive
        self.avg_rtt = avg_rtt
        self.packet_loss = 0.0 if is_alive else 1.0


async def test_ping_success_returns_rtt():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=1000)
    probe = PingProbe(ctx, packet_size=56)
    fake = _FakeIcmpHost(is_alive=True, avg_rtt=12.5)
    with patch("nettest.probes.ping.async_ping", new=AsyncMock(return_value=fake)):
        res = await probe.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is True
    assert res.duration_ms == 12.5
    assert res.metrics["packet_loss"] == 0.0


async def test_ping_failure_returns_unreachable():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=500)
    probe = PingProbe(ctx, packet_size=56)
    fake = _FakeIcmpHost(is_alive=False, avg_rtt=0.0)
    with patch("nettest.probes.ping.async_ping", new=AsyncMock(return_value=fake)):
        res = await probe.run(Target(kind="host", host="10.255.255.1"), cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "unreachable"
