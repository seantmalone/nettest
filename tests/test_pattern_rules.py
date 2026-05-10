from datetime import UTC, datetime, timedelta

from nettest.config import Patterns
from nettest.patterns.rules import (
    detect_correlated_loss,
    detect_dns_only_fail,
    detect_latency_spike,
    detect_micro_outage,
    detect_stream_stall,
)
from nettest.patterns.window import RollingWindow
from nettest.types import Result


def _r(t, probe="ping", target="1.1.1.1", ok=True, ms=1.0, metrics=None):
    return Result(
        ts=t, host="h", probe=probe, target=target,
        ok=ok, duration_ms=ms, metrics=metrics or {},
    )


def test_micro_outage_fires_on_three_consecutive_fails():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow()
    w.add(_r(base, ok=True))
    w.add(_r(base + timedelta(milliseconds=200), ok=False))
    w.add(_r(base + timedelta(milliseconds=400), ok=False))
    w.add(_r(base + timedelta(milliseconds=600), ok=False))
    cfg = Patterns()
    e = detect_micro_outage(w, last=w.results[-1], cfg=cfg.micro_outage)
    assert e is not None
    assert e.kind == "micro_outage"
    assert e.severity == "warn"


def test_micro_outage_does_not_fire_on_two_fails():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow()
    w.add(_r(base, ok=False))
    w.add(_r(base + timedelta(milliseconds=200), ok=False))
    cfg = Patterns()
    e = detect_micro_outage(w, last=w.results[-1], cfg=cfg.micro_outage)
    assert e is None


def test_correlated_loss_fires_when_three_targets_fail():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow()
    w.add(_r(base, target="a", ok=False))
    w.add(_r(base + timedelta(milliseconds=300), target="b", ok=False))
    w.add(_r(base + timedelta(milliseconds=900), target="c", ok=False))
    cfg = Patterns()
    e = detect_correlated_loss(w, last=w.results[-1], cfg=cfg.correlated_loss)
    assert e is not None
    assert e.severity == "critical"


def test_dns_only_fail_fires():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow()
    w.add(_r(base, probe="dns_cached", target="r1", ok=False))
    w.add(_r(base + timedelta(milliseconds=300), probe="dns_cached", target="r2", ok=False))
    w.add(_r(base + timedelta(milliseconds=400), probe="ping", target="x", ok=True))
    cfg = Patterns()
    e = detect_dns_only_fail(w, last=w.results[-1], cfg=cfg.dns_only_fail)
    assert e is not None


def test_latency_spike_fires():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow()
    for i in range(40):
        w.add(_r(base + timedelta(milliseconds=i * 10), ms=10.0))
    spike = _r(base + timedelta(milliseconds=420), ms=200.0)
    w.add(spike)
    cfg = Patterns()
    e = detect_latency_spike(w, last=spike, cfg=cfg.latency_spike)
    assert e is not None


def test_stream_stall_fires_on_two_stalls_in_minute():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow(window_s=120)
    w.add(_r(base, probe="stream", target="cdn", metrics={"stall_count": 2}))
    cfg = Patterns()
    e = detect_stream_stall(w, last=w.results[-1], cfg=cfg.stream_stall)
    assert e is not None
