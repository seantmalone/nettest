import asyncio
from datetime import UTC, datetime, timedelta

from nettest.bus import ResultBus
from nettest.config import Patterns
from nettest.events import Event
from nettest.patterns.detector import PatternDetector
from nettest.types import Result


async def test_detector_emits_micro_outage_event():
    bus = ResultBus()
    fired: list[Event] = []
    det = PatternDetector(bus=bus, cfg=Patterns(), on_event=fired.append)
    task = asyncio.create_task(det.run())
    base = datetime.now(UTC)
    await bus.publish(Result(
        ts=base, host="h", probe="ping", target="x",
        ok=True, duration_ms=1.0,
    ))
    for t_ms in (200, 400, 600):
        await bus.publish(Result(
            ts=base + timedelta(milliseconds=t_ms),
            host="h", probe="ping", target="x",
            ok=False, duration_ms=100.0,
        ))
    await asyncio.sleep(0.05)
    det.stop()
    await task
    assert any(e.kind == "micro_outage" for e in fired)


async def test_detector_tags_contributing_result():
    bus = ResultBus()
    fired: list[Event] = []
    det = PatternDetector(bus=bus, cfg=Patterns(), on_event=fired.append)
    task = asyncio.create_task(det.run())
    base = datetime.now(UTC)
    last_result: Result | None = None
    for t_ms in (0, 200, 400, 600):
        r = Result(
            ts=base + timedelta(milliseconds=t_ms),
            host="h", probe="ping", target="x",
            ok=(t_ms == 0),
            duration_ms=100.0 if t_ms > 0 else 1.0,
        )
        await bus.publish(r)
        last_result = r
    await asyncio.sleep(0.05)
    det.stop()
    await task
    assert any(e.kind == "micro_outage" for e in fired)
    assert last_result is not None
    assert "micro_outage" in last_result.tags


async def test_detector_does_not_emit_on_clean_stream():
    bus = ResultBus()
    fired: list[Event] = []
    det = PatternDetector(bus=bus, cfg=Patterns(), on_event=fired.append)
    task = asyncio.create_task(det.run())
    base = datetime.now(UTC)
    for i in range(20):
        await bus.publish(Result(
            ts=base + timedelta(milliseconds=i * 50),
            host="h", probe="ping", target="x",
            ok=True, duration_ms=10.0,
        ))
    await asyncio.sleep(0.05)
    det.stop()
    await task
    assert fired == []
