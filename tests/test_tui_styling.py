from nettest.config import ProbeThreshold
from nettest.tui.styling import (
    ICONS,
    SEVERITY_RANK,
    classify_probe,
    format_ms,
    sparkline_string,
)


def test_format_ms_returns_em_dash_for_none():
    assert format_ms(None) == "—"


def test_format_ms_uses_one_decimal_under_10ms():
    assert format_ms(0.4) == "0.4ms"
    assert format_ms(9.9) == "9.9ms"


def test_format_ms_uses_integer_at_or_above_10ms():
    assert format_ms(10) == "10ms"
    assert format_ms(12.7) == "13ms"
    assert format_ms(123.456) == "123ms"


def test_format_ms_without_unit_drops_suffix():
    assert format_ms(5.0, with_unit=False) == "5.0"
    assert format_ms(150.0, with_unit=False) == "150"


def test_classify_probe_returns_severity():
    th = ProbeThreshold(warn_loss_pct=1, crit_loss_pct=5, warn_p95_ms=50, crit_p95_ms=200)
    assert classify_probe(loss_pct=0, p95_ms=10, th=th) == "ok"
    assert classify_probe(loss_pct=2, p95_ms=10, th=th) == "warn"
    assert classify_probe(loss_pct=10, p95_ms=10, th=th) == "critical"
    assert classify_probe(loss_pct=0, p95_ms=300, th=th) == "critical"


def test_severity_rank_orders_critical_above_warn():
    assert SEVERITY_RANK["critical"] > SEVERITY_RANK["warn"] > SEVERITY_RANK["ok"]


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
