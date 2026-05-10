import asyncio
from datetime import UTC, datetime

import pytest

from nettest.bus import ResultBus
from nettest.types import Result


def make_result(probe: str = "ping") -> Result:
    return Result(
        ts=datetime.now(UTC),
        host="h",
        probe=probe,
        target="1.1.1.1",
        ok=True,
        duration_ms=1.0,
    )


async def test_subscriber_receives_published_result():
    bus = ResultBus()
    q = bus.subscribe("test", drop_policy="never")
    await bus.publish(make_result())
    got = await asyncio.wait_for(q.get(), timeout=1.0)
    assert got.probe == "ping"


async def test_multiple_subscribers_each_get_copy():
    bus = ResultBus()
    a = bus.subscribe("a", drop_policy="never")
    b = bus.subscribe("b", drop_policy="never")
    await bus.publish(make_result())
    assert (await a.get()).probe == "ping"
    assert (await b.get()).probe == "ping"


async def test_drop_oldest_drops_when_full():
    bus = ResultBus()
    q = bus.subscribe("ui", drop_policy="drop_oldest", max_depth=3)
    for _ in range(10):
        await bus.publish(make_result())
    assert q.qsize() == 3
    assert bus.drop_count("ui") == 7


async def test_never_policy_blocks_then_succeeds_when_consumed():
    bus = ResultBus()
    q = bus.subscribe("storage", drop_policy="never", max_depth=2)
    await bus.publish(make_result())
    await bus.publish(make_result())
    publisher = asyncio.create_task(bus.publish(make_result()))
    await asyncio.sleep(0.01)
    assert not publisher.done()
    await q.get()
    await asyncio.wait_for(publisher, timeout=1.0)


async def test_subscribe_rejects_duplicate_name():
    bus = ResultBus()
    bus.subscribe("a", drop_policy="never")
    with pytest.raises(ValueError, match="already subscribed"):
        bus.subscribe("a", drop_policy="never")


async def test_unsubscribe_removes_subscriber():
    bus = ResultBus()
    bus.subscribe("a", drop_policy="never")
    assert "a" in bus.subscribers()
    bus.unsubscribe("a")
    assert "a" not in bus.subscribers()
    # Can re-subscribe with the same name
    bus.subscribe("a", drop_policy="never")
    assert "a" in bus.subscribers()
