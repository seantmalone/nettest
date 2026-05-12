"""Compute high-level health categories from per-target snapshots."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal

from nettest.config import ProbeThreshold, Thresholds
from nettest.tui.aggregator import TargetSnapshot

Severity = Literal["ok", "warn", "critical"]

# `host:` / `ping:` etc prefixes that target labels sometimes carry.
_LABEL_PREFIX = re.compile(r"^[a-z_]+:")


def _extract_host(target: str) -> str:
    """Strip kind-prefix (e.g. ``host:10.0.0.1`` -> ``10.0.0.1``)."""
    return _LABEL_PREFIX.sub("", target).strip()


def is_lan_target(target: str) -> bool:
    """Classify a ping target as LAN (private/loopback/link-local) vs Internet.

    Prefer parsing the target as an IP and using RFC 1918 / link-local /
    loopback ranges — the gateway is the canonical LAN target but it is
    often configured as a bare IP (e.g. ``10.200.0.1``), which the old
    substring match on ``"gateway"`` misclassified as Internet. Fall back
    to the substring heuristic for hostname targets that aren't bare IPs.
    """
    host = _extract_host(target)
    if "/" in host:
        host = host.split("/", 1)[0]
    if host.count(":") == 1 and "." in host:
        host = host.split(":", 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "gateway" in target.lower()
    return ip.is_private or ip.is_loopback or ip.is_link_local


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
            sev = "critical"
        elif s.loss_pct >= th.warn_loss_pct and sev != "critical":
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
        s for (p, t), s in snaps.items() if p == "ping" and is_lan_target(t)
    ]
    sev, loss = _worst(lan_snaps, th.ping)
    rows.append(HealthRow(
        "LAN", sev,
        f"gateway loss {loss:.1f}%" if lan_snaps else "no gateway target",
    ))

    inet_snaps = [
        s for (p, t), s in snaps.items() if p == "ping" and not is_lan_target(t)
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
