from nettest.tui.aggregator import TargetSnapshot
from nettest.tui.health import compute_health_summary, is_lan_target


def _snap(loss: float = 0.0, p95: float = 10.0, last_ok: bool = True) -> TargetSnapshot:
    return TargetSnapshot(
        last_ms=10, p50_ms=10, p95_ms=p95, p99_ms=p95, min_ms=10, max_ms=p95,
        loss_pct=loss, count=10, sparkline=[None] * 10, last_ok=last_ok,
    )


def test_health_summary_all_categories_present():
    snaps = {
        ("ping", "gateway"): _snap(),
        ("ping", "1.1.1.1"): _snap(),
        ("dns_cached", "1.1.1.1/google.com"): _snap(),
        ("http", "https://google.com"): _snap(),
        ("wifi", "local"): _snap(),
        ("stream", "cdn"): _snap(),
    }
    summary = compute_health_summary(snaps)
    cats = {row.name for row in summary}
    assert {"LAN", "Internet", "DNS", "Wi-Fi", "Streaming"}.issubset(cats)


def test_lan_warn_when_gateway_lossy():
    snaps = {("ping", "gateway"): _snap(loss=2.0)}
    summary = compute_health_summary(snaps)
    lan = next(r for r in summary if r.name == "LAN")
    assert lan.severity == "warn"


def test_is_lan_target_classifies_rfc1918_ip_as_lan():
    # Regression: previously the "gateway" substring heuristic mis-classified
    # a bare-IP gateway like 10.200.0.1 as Internet, because the label has no
    # "gateway" substring. Driving partitioning from the IP fixes this.
    assert is_lan_target("host:10.200.0.1") is True
    assert is_lan_target("10.200.0.1") is True
    assert is_lan_target("192.168.1.1") is True
    assert is_lan_target("127.0.0.1") is True
    assert is_lan_target("169.254.0.1") is True


def test_is_lan_target_classifies_public_ip_as_internet():
    assert is_lan_target("1.1.1.1") is False
    assert is_lan_target("host:8.8.8.8") is False
    assert is_lan_target("ping:9.9.9.9") is False


def test_is_lan_target_falls_back_to_gateway_substring_for_hostnames():
    assert is_lan_target("gateway") is True
    assert is_lan_target("home-gateway") is True
    assert is_lan_target("google.com") is False


def test_lan_critical_when_bare_ip_gateway_loses_packets():
    snaps = {("ping", "host:10.200.0.1"): _snap(loss=10.0)}
    summary = compute_health_summary(snaps)
    lan = next(r for r in summary if r.name == "LAN")
    inet = next(r for r in summary if r.name == "Internet")
    assert lan.severity == "critical"
    # The same target must NOT also be counted in Internet.
    assert inet.detail == "no internet target"
