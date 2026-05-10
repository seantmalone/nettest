"""Compute high-level health categories from per-target snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nettest.config import ProbeThreshold, Thresholds
from nettest.tui.aggregator import TargetSnapshot

Severity = Literal["ok", "warn", "crit"]


@dataclass(slots=True)
class HealthRow:
    name: str
    severity: Severity
    detail: str


def _worst(
    snaps: list[TargetSnapshot], th: ProbeThreshold,
) -> tuple[Severity, float]:
    if not snaps:
        return "ok", 0.0
    sev: Severity = "ok"
    worst_loss = 0.0
    for s in snaps:
        if s.loss_pct >= th.crit_loss_pct:
            sev = "crit"
        elif s.loss_pct >= th.warn_loss_pct and sev != "crit":
            sev = "warn"
        worst_loss = max(worst_loss, s.loss_pct)
    return sev, worst_loss


def compute_health_summary(
    snaps: dict[tuple[str, str], TargetSnapshot],
    thresholds: Thresholds | None = None,
) -> list[HealthRow]:
    th = thresholds or Thresholds()
    by_probe: dict[str, list[TargetSnapshot]] = {}
    for (probe, _t), s in snaps.items():
        by_probe.setdefault(probe, []).append(s)

    rows: list[HealthRow] = []

    lan_snaps = [
        s for (p, t), s in snaps.items() if p == "ping" and "gateway" in t.lower()
    ]
    sev, loss = _worst(lan_snaps, th.ping)
    rows.append(HealthRow(
        "LAN", sev,
        f"gateway loss {loss:.1f}%" if lan_snaps else "no gateway target",
    ))

    inet_snaps = [
        s for (p, t), s in snaps.items() if p == "ping" and "gateway" not in t.lower()
    ]
    sev, loss = _worst(inet_snaps, th.ping)
    rows.append(HealthRow(
        "Internet", sev,
        f"public-IP loss {loss:.1f}%" if inet_snaps else "no internet target",
    ))

    dns_snaps = by_probe.get("dns_cached", []) + by_probe.get("dns_uncached", [])
    sev, loss = _worst(dns_snaps, th.dns_cached)
    rows.append(HealthRow(
        "DNS", sev,
        f"resolver loss {loss:.1f}%" if dns_snaps else "no DNS target",
    ))

    wifi_snaps = by_probe.get("wifi", [])
    if wifi_snaps and all(s.last_ok for s in wifi_snaps):
        wifi_sev: Severity = "ok"
    elif wifi_snaps:
        wifi_sev = "warn"
    else:
        wifi_sev = "ok"
    rows.append(HealthRow(
        "Wi-Fi", wifi_sev,
        "samples ok" if wifi_snaps and wifi_sev == "ok" else "no samples",
    ))

    stream_snaps = by_probe.get("stream", [])
    sev, _ = _worst(stream_snaps, th.http)
    rows.append(HealthRow(
        "Streaming", sev,
        "running" if stream_snaps else "no stream test",
    ))

    return rows
