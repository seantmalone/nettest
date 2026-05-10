import json
from datetime import UTC, datetime
from pathlib import Path

from nettest.events import Event
from nettest.tui.aggregator import TargetAggregator
from nettest.tui.detail import write_snapshot
from nettest.types import Result


def _ts():
    return datetime.now(UTC)


def test_write_snapshot_produces_json_with_aggregates_and_events(tmp_path: Path):
    agg = TargetAggregator(window_s=30, sparkline_buckets=10)
    for i in range(5):
        agg.record(Result(
            ts=_ts(), host="h", probe="ping", target="x",
            ok=True, duration_ms=float(i + 1),
        ))
    aggs = {("ping", "x"): agg}
    events = [Event(
        ts_start=_ts(), ts_end=_ts(), kind="micro_outage",
        severity="warn", summary="s",
    )]
    path = write_snapshot(
        directory=str(tmp_path), hostname="h", aggregators=aggs, events=events,
    )
    data = json.loads(Path(path).read_text())
    assert data["hostname"] == "h"
    assert data["aggregators"][0]["probe"] == "ping"
    assert data["events"][0]["kind"] == "micro_outage"
