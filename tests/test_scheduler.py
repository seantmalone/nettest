import asyncio
from datetime import UTC, datetime

from nettest.bus import ResultBus
from nettest.probes.base import Probe, ProbeContext
from nettest.scheduler import Scheduler
from nettest.types import Result, Target


class _CountingProbe(Probe):
    name = "count"

    def __init__(self, ctx: ProbeContext):
        super().__init__(ctx)
        self.calls = 0

    async def measure(self, target: Target) -> Result:
        self.calls += 1
        return Result(
            ts=datetime.now(UTC), host="h", probe=self.name,
            target=target.label(), ok=True, duration_ms=0.1,
        )


async def test_scheduler_runs_probe_at_interval():
    bus = ResultBus()
    q = bus.subscribe("sink", drop_policy="never")
    ctx = ProbeContext(hostname="h", interval_ms=50, timeout_ms=1000)
    probe = _CountingProbe(ctx)
    sched = Scheduler(bus=bus)
    sched.add(probe, [Target(kind="host", host="1.1.1.1")])

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.18)
    sched.stop()
    await task

    assert probe.calls >= 3
    assert q.qsize() >= 3


async def test_scheduler_isolates_probe_failures():
    bus = ResultBus()
    bus.subscribe("sink", drop_policy="never")

    class _Bad(_CountingProbe):
        name = "bad"

        async def measure(self, target):
            self.calls += 1
            raise RuntimeError("nope")

    ctx = ProbeContext(hostname="h", interval_ms=20, timeout_ms=500)
    bad = _Bad(ctx)
    good = _CountingProbe(ctx)
    sched = Scheduler(bus=bus)
    sched.add(bad, [Target(kind="host", host="1.1.1.1")])
    sched.add(good, [Target(kind="host", host="2.2.2.2")])

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.2)
    sched.stop()
    await task

    assert good.calls > 0
    assert bad.calls > 0


async def test_scheduler_pause_and_resume():
    bus = ResultBus()
    q = bus.subscribe("sink", drop_policy="never")
    ctx = ProbeContext(hostname="h", interval_ms=20, timeout_ms=500)
    probe = _CountingProbe(ctx)
    sched = Scheduler(bus=bus)
    sched.add(probe, [Target(kind="host", host="1.1.1.1")])

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.05)
    before = probe.calls
    sched.pause()
    await asyncio.sleep(0.1)
    paused = probe.calls
    sched.resume()
    await asyncio.sleep(0.1)
    sched.stop()
    await task

    assert paused - before <= 1
    assert probe.calls > paused

    drained: list[Result] = []
    while not q.empty():
        drained.append(q.get_nowait())
    kinds = {r.probe for r in drained}
    assert "_paused" in kinds and "_resumed" in kinds
