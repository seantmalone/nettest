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


def test_aggregator_snapshot_exposes_p99_min_max():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    agg = TargetAggregator(window_s=30, sparkline_buckets=10)
    samples = [10.0, 12.0, 14.0, 11.0, 13.0, 15.0, 9.0, 16.0, 100.0, 12.0]
    for i, ms in enumerate(samples):
        agg.record(_r(base + timedelta(seconds=i), ms))
    snap = agg.snapshot(now=base + timedelta(seconds=10))
    assert snap.min_ms == 9.0
    assert snap.max_ms == 100.0
    assert snap.p99_ms is not None
    assert snap.p99_ms >= snap.p95_ms
    assert snap.p99_ms <= 100.0


def test_aggregator_snapshot_window_override_uses_subset():
    # `retain_s` keeps a longer history than the default window so the
    # `[`/`]` keys can ask for a wider sparkline without losing data.
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    agg = TargetAggregator(window_s=30, sparkline_buckets=12, retain_s=900)
    for i in range(120):
        agg.record(_r(base + timedelta(seconds=i), float(i + 1)))
    snap_30 = agg.snapshot(now=base + timedelta(seconds=120))
    snap_5m = agg.snapshot(
        now=base + timedelta(seconds=120), window_s=300, sparkline_buckets=20,
    )
    assert snap_30.count < snap_5m.count
    assert snap_5m.count == 120
    assert len(snap_5m.sparkline) == 20
