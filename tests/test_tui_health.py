from nettest.tui.aggregator import TargetSnapshot
from nettest.tui.health import compute_health_summary


def _snap(loss: float = 0.0, p95: float = 10.0, last_ok: bool = True) -> TargetSnapshot:
    return TargetSnapshot(
        last_ms=10, p50_ms=10, p95_ms=p95, loss_pct=loss,
        count=10, sparkline=[None] * 10, last_ok=last_ok,
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
