import asyncio
from unittest.mock import AsyncMock, patch

from nettest.probes.base import ProbeContext
from nettest.probes.mtu import MtuProbe
from nettest.types import Target


async def test_mtu_finds_largest_passing_size():
    ctx = ProbeContext(hostname="h", interval_ms=300000, timeout_ms=2000)
    probe = MtuProbe(ctx, sizes=[1500, 1472, 1400, 1200, 1000, 576])

    async def fake_send(host: str, size: int) -> bool:
        return size <= 1400

    with patch.object(probe, "_ping_df", new=AsyncMock(side_effect=fake_send)):
        res = await probe.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is True
    assert res.metrics["mtu"] == 1400


async def test_mtu_returns_failure_when_all_sizes_fail():
    ctx = ProbeContext(hostname="h", interval_ms=300000, timeout_ms=2000)
    probe = MtuProbe(ctx, sizes=[1500, 1000, 576])
    with patch.object(probe, "_ping_df", new=AsyncMock(return_value=False)):
        res = await probe.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is False
