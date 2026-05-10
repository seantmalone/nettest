from datetime import UTC, datetime, timedelta

from nettest.patterns.window import RollingWindow
from nettest.types import Result


def _r(ts: datetime, probe: str = "ping", target: str = "1.1.1.1", ok: bool = True) -> Result:
    return Result(ts=ts, host="h", probe=probe, target=target, ok=ok, duration_ms=1.0)


def test_rolling_window_evicts_old_entries():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow(window_s=10)
    w.add(_r(base))
    w.add(_r(base + timedelta(seconds=5)))
    w.add(_r(base + timedelta(seconds=12)))
    w.evict(base + timedelta(seconds=12))
    assert len(w.results) == 2


def test_rolling_window_query_by_probe_target():
    base = datetime(2026, 5, 10, 18, 0, 0, tzinfo=UTC)
    w = RollingWindow(window_s=30)
    w.add(_r(base, probe="ping", target="a"))
    w.add(_r(base + timedelta(seconds=1), probe="ping", target="b"))
    w.add(_r(base + timedelta(seconds=2), probe="dns_cached", target="a"))
    a_ping = w.recent_for(
        probe="ping", target="a", window_s=30, now=base + timedelta(seconds=2),
    )
    assert len(a_ping) == 1
    assert a_ping[0].target == "a"
