import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from nettest.bus import ResultBus
from nettest.storage.jsonl_sink import JsonlSink
from nettest.types import Result


async def test_jsonl_sink_writes_one_line_per_result(tmp_path: Path):
    bus = ResultBus()
    sink = JsonlSink(bus=bus, data_dir=tmp_path, flush_interval_ms=20)
    task = asyncio.create_task(sink.run())

    for i in range(3):
        await bus.publish(Result(
            ts=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
            host="h", probe=f"p{i}", target="x", ok=True, duration_ms=1.0,
        ))
    await asyncio.sleep(0.1)
    sink.stop()
    await task

    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert {p["probe"] for p in parsed} == {"p0", "p1", "p2"}


async def test_jsonl_sink_rotates_on_utc_midnight(tmp_path: Path):
    bus = ResultBus()
    sink = JsonlSink(bus=bus, data_dir=tmp_path, flush_interval_ms=10)
    task = asyncio.create_task(sink.run())

    await bus.publish(Result(
        ts=datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC),
        host="h", probe="ping", target="x", ok=True, duration_ms=1.0,
    ))
    await asyncio.sleep(0.05)
    await bus.publish(Result(
        ts=datetime(2026, 5, 11, 0, 0, 1, tzinfo=UTC),
        host="h", probe="ping", target="x", ok=True, duration_ms=1.0,
    ))
    await asyncio.sleep(0.05)
    sink.stop()
    await task

    files = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert files == ["2026-05-10.jsonl", "2026-05-11.jsonl"]
