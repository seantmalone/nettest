from nettest.config import ProbeThreshold
from nettest.tui.styling import ICONS, classify_probe, sparkline_string


def test_classify_probe_returns_severity():
    th = ProbeThreshold(warn_loss_pct=1, crit_loss_pct=5, warn_p95_ms=50, crit_p95_ms=200)
    assert classify_probe(loss_pct=0, p95_ms=10, th=th) == "ok"
    assert classify_probe(loss_pct=2, p95_ms=10, th=th) == "warn"
    assert classify_probe(loss_pct=10, p95_ms=10, th=th) == "crit"
    assert classify_probe(loss_pct=0, p95_ms=300, th=th) == "crit"


def test_sparkline_renders_unicode_bars():
    s = sparkline_string([1, 2, 3, None, 4])
    assert len(s) == 5
    assert " " in s


def test_icons_present_for_each_probe():
    for k in (
        "ping", "dns_cached", "dns_uncached", "http", "tcp_connect",
        "traceroute", "stream", "mtu", "wifi", "bandwidth",
    ):
        assert k in ICONS
