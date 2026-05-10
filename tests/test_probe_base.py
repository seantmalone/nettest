import asyncio
from datetime import UTC, datetime

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


class _FakeProbe(Probe):
    name = "fake"

    def __init__(self, ctx: ProbeContext, *, fail: bool = False, delay: float = 0):
        super().__init__(ctx)
        self.fail = fail
        self.delay = delay

    async def measure(self, target: Target) -> Result:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        return Result(
            ts=datetime.now(UTC),
            host=self.ctx.hostname,
            probe=self.name,
            target=target.label(),
            ok=True,
            duration_ms=1.0,
        )


async def test_probe_run_returns_result_on_success():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=1000)
    p = _FakeProbe(ctx)
    res = await p.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is True


async def test_probe_run_returns_failure_result_on_exception():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=1000)
    p = _FakeProbe(ctx, fail=True)
    res = await p.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is False
    assert "boom" in (res.error or "")


async def test_probe_run_returns_timeout_result_when_exceeded():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=50)
    p = _FakeProbe(ctx, delay=0.5)
    res = await p.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "timeout"


async def test_probe_run_honors_cancel_event():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=5000)
    p = _FakeProbe(ctx, delay=10)
    cancel = asyncio.Event()
    cancel.set()
    res = await p.run(Target(kind="host", host="1.1.1.1"), cancel=cancel)
    assert res.ok is False
    assert res.error == "cancelled"
