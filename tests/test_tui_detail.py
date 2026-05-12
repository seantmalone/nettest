import json
from datetime import UTC, datetime
from pathlib import Path

from nettest.events import Event
from nettest.sysinfo import SysInfo
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
    # New per-target fields surfaced now that TargetSnapshot carries them.
    first = data["aggregators"][0]
    assert "p99_ms" in first
    assert "min_ms" in first
    assert "max_ms" in first


def test_write_snapshot_redact_scrubs_identifying_fields(tmp_path: Path):
    sysinfo = SysInfo(
        wifi_ssid="MyHomeNet",
        wifi_bssid="aa:bb:cc:dd:ee:ff",
        public_ip="203.0.113.5",
    )
    path = write_snapshot(
        directory=str(tmp_path), hostname="h",
        aggregators={}, events=[], sysinfo=sysinfo, redact=True,
    )
    data = json.loads(Path(path).read_text())
    si = data["sysinfo"]
    assert si["public_ip"] == "<redacted>"
    assert si["wifi_bssid"] == "<redacted>"
    assert si["wifi_ssid"] == "<redacted>"


def test_write_snapshot_no_redact_keeps_values(tmp_path: Path):
    sysinfo = SysInfo(public_ip="203.0.113.5")
    path = write_snapshot(
        directory=str(tmp_path), hostname="h",
        aggregators={}, events=[], sysinfo=sysinfo, redact=False,
    )
    data = json.loads(Path(path).read_text())
    assert data["sysinfo"]["public_ip"] == "203.0.113.5"
