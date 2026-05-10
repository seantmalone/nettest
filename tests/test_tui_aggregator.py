from datetime import UTC, datetime, timedelta

from nettest.tui.aggregator import TargetAggregator
from nettest.types import Result


def _r(t: datetime, ms: float, ok: bool = True) -> Result:
    return Result(ts=t, host="h", probe="ping", target="1.1.1.1", ok=ok, duration_ms=ms)


def test_aggregator_tracks_last_p50_p95_loss():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    agg = TargetAggregator(window_s=30, sparkline_buckets=10)
    for i, ms in enumerate([10, 12, 14, 11, 13, 15, 9, 16, 100, 12]):
        agg.record(_r(base + timedelta(seconds=i), ms))
    snap = agg.snapshot(now=base + timedelta(seconds=10))
    assert snap.last_ms == 12
    assert snap.p50_ms < snap.p95_ms
    assert snap.loss_pct == 0.0


def test_aggregator_loss_percentage():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    agg = TargetAggregator(window_s=30, sparkline_buckets=10)
    for i in range(10):
        agg.record(_r(base + timedelta(seconds=i), 1.0, ok=(i % 2 == 0)))
    snap = agg.snapshot(now=base + timedelta(seconds=10))
    assert snap.loss_pct == 50.0


def test_aggregator_sparkline_has_buckets():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    agg = TargetAggregator(window_s=10, sparkline_buckets=5)
    for i in range(10):
        agg.record(_r(base + timedelta(seconds=i), float(i + 1)))
    snap = agg.snapshot(now=base + timedelta(seconds=10))
    assert len(snap.sparkline) == 5
