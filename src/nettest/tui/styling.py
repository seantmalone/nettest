"""Color, icon, and sparkline helpers."""
from __future__ import annotations

from typing import Literal

from nettest.config import ProbeThreshold

# TUI status severity. Matches `Event.severity` for the "bad" levels (warn,
# critical); `ok` is the health-status counterpart to event-severity `info`.
Severity = Literal["ok", "warn", "critical"]

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
    "ok":       "#3ecf8e",
    "warn":     "#f5c344",
    "critical": "#e5484d",
}

SEVERITY_RANK: dict[str, int] = {"ok": 0, "warn": 1, "critical": 2}

_BARS = " ▁▂▃▄▅▆▇█"
_MISSING_BUCKET = "·"  # distinct from low-latency "▁" so "no data" doesn't read as healthy


def format_ms(value: float | None, with_unit: bool = True) -> str:
    """Format a millisecond duration.

    Sub-millisecond values are clamped to ``<1ms`` — the underlying clock
    jitter dominates anything below 1ms, so reporting "0.4ms" is false
    precision. For ``with_unit=False`` the unit suffix is dropped and
    sub-ms collapses to ``<1`` so the column still aligns.
    """
    if value is None:
        return "—"
    if value < 1:
        return "<1ms" if with_unit else "<1"
    s = f"{value:.1f}" if value < 100 else f"{value:.0f}"
    return f"{s}ms" if with_unit else s


def classify_probe(
    *, loss_pct: float, p95_ms: float | None, th: ProbeThreshold,
) -> Severity:
    if loss_pct >= th.crit_loss_pct:
        return "critical"
    if p95_ms is not None and p95_ms >= th.crit_p95_ms:
        return "critical"
    if loss_pct >= th.warn_loss_pct:
        return "warn"
    if p95_ms is not None and p95_ms >= th.warn_p95_ms:
        return "warn"
    return "ok"


def sparkline_string(values: list[float | None]) -> str:
    """Render a sparkline. Missing buckets use ``·`` so absence is visible."""
    nums = [v for v in values if v is not None]
    if not nums:
        return _MISSING_BUCKET * len(values)
    lo = min(nums)
    hi = max(nums)
    rng = max(hi - lo, 1e-6)
    out = []
    for v in values:
        if v is None:
            out.append(_MISSING_BUCKET)
        else:
            idx = min(len(_BARS) - 1, int(((v - lo) / rng) * (len(_BARS) - 1)))
            out.append(_BARS[max(idx, 1)])
    return "".join(out)
