"""Color, icon, and sparkline helpers."""
from __future__ import annotations

from typing import Literal

from nettest.config import ProbeThreshold

Severity = Literal["ok", "warn", "crit"]

ICONS: dict[str, str] = {
    "ping":         "\U000F04D5",
    "dns_cached":   "\U000F01E7",
    "dns_uncached": "\U000F01E7",
    "http":         "\U000F059F",
    "tcp_connect":  "\U000F0319",
    "traceroute":   "\U000F0200",
    "stream":       "\U000F057E",
    "mtu":          "\U000F0F87",
    "bandwidth":    "\U000F0570",
    "wifi":         "\U000F05A9",
}

ASCII_ICONS: dict[str, str] = {
    "ping": "[ping]", "dns_cached": "[dns-c]", "dns_uncached": "[dns-u]",
    "http": "[http]", "tcp_connect": "[tcp]", "traceroute": "[trace]",
    "stream": "[strm]", "mtu": "[mtu]", "bandwidth": "[bw]", "wifi": "[wifi]",
}

COLORS = {
    "ok":   "#3ecf8e",
    "warn": "#f5c344",
    "crit": "#e5484d",
}

_BARS = " ▁▂▃▄▅▆▇█"


def classify_probe(
    *, loss_pct: float, p95_ms: float | None, th: ProbeThreshold,
) -> Severity:
    if loss_pct >= th.crit_loss_pct:
        return "crit"
    if p95_ms is not None and p95_ms >= th.crit_p95_ms:
        return "crit"
    if loss_pct >= th.warn_loss_pct:
        return "warn"
    if p95_ms is not None and p95_ms >= th.warn_p95_ms:
        return "warn"
    return "ok"


def sparkline_string(values: list[float | None]) -> str:
    nums = [v for v in values if v is not None]
    if not nums:
        return " " * len(values)
    lo = min(nums)
    hi = max(nums)
    rng = max(hi - lo, 1e-6)
    out = []
    for v in values:
        if v is None:
            out.append(" ")
        else:
            idx = min(len(_BARS) - 1, int(((v - lo) / rng) * (len(_BARS) - 1)))
            out.append(_BARS[max(idx, 1)])
    return "".join(out)
