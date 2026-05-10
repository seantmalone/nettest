"""Pattern detection rules — each takes a window + last result and returns an Event or None."""
from __future__ import annotations

from nettest.config import (
    CorrelatedLoss,
    DnsOnlyFail,
    LatencySpike,
    MicroOutage,
    MtuChange,
    StreamStall,
    WifiDrop,
)
from nettest.events import Event
from nettest.patterns.window import RollingWindow
from nettest.types import Result


def detect_micro_outage(w: RollingWindow, last: Result, cfg: MicroOutage) -> Event | None:
    if last.ok:
        return None
    recent = w.recent_for(
        probe=last.probe, target=last.target,
        window_s=cfg.window_ms / 1000, now=last.ts,
    )
    consecutive = 0
    for r in reversed(recent):
        if r.ok:
            break
        consecutive += 1
    if consecutive < cfg.min_consecutive_fails:
        return None
    return Event(
        ts_start=recent[-consecutive].ts if consecutive else last.ts,
        ts_end=last.ts,
        kind="micro_outage",
        severity="warn",
        summary=(
            f"{consecutive} consecutive {last.probe} fails to {last.target} "
            f"in <{cfg.window_ms}ms"
        ),
        details={"probe": last.probe, "target": last.target, "fails": consecutive},
    )


def detect_correlated_loss(
    w: RollingWindow, last: Result, cfg: CorrelatedLoss,
) -> Event | None:
    recent = w.recent_for(window_s=cfg.window_ms / 1000, now=last.ts)
    failed_targets = {r.target for r in recent if not r.ok}
    if len(failed_targets) < cfg.min_targets:
        return None
    return Event(
        ts_start=recent[0].ts if recent else last.ts,
        ts_end=last.ts,
        kind="correlated_loss",
        severity="critical",
        summary=f"{len(failed_targets)} distinct targets failed within {cfg.window_ms}ms",
        details={"targets": sorted(failed_targets), "window_ms": cfg.window_ms},
    )


def detect_dns_only_fail(w: RollingWindow, last: Result, cfg: DnsOnlyFail) -> Event | None:
    recent = w.recent_for(window_s=cfg.window_ms / 1000, now=last.ts)
    dns_fails = sum(1 for r in recent if r.probe.startswith("dns") and not r.ok)
    other_fails = sum(1 for r in recent if not r.probe.startswith("dns") and not r.ok)
    if dns_fails < cfg.min_dns_fails or other_fails > cfg.max_other_fails:
        return None
    return Event(
        ts_start=recent[0].ts if recent else last.ts,
        ts_end=last.ts,
        kind="dns_only_fail",
        severity="warn",
        summary=(
            f"{dns_fails} DNS failures with {other_fails} other failures "
            f"in {cfg.window_ms}ms"
        ),
        details={"dns_fails": dns_fails, "other_fails": other_fails},
    )


def detect_latency_spike(w: RollingWindow, last: Result, cfg: LatencySpike) -> Event | None:
    if not last.ok:
        return None
    samples = [
        r.duration_ms for r in w.recent_for(probe=last.probe, target=last.target, now=last.ts)
        if r.ok and r.duration_ms is not None
    ]
    if len(samples) < cfg.min_samples:
        return None
    samples_sorted = sorted(samples[:-1])
    if not samples_sorted:
        return None
    p95_idx = int(0.95 * (len(samples_sorted) - 1))
    p95 = samples_sorted[p95_idx]
    if p95 == 0 or last.duration_ms < p95 * cfg.p95_multiplier:
        return None
    return Event(
        ts_start=last.ts,
        ts_end=last.ts,
        kind="latency_spike",
        severity="warn",
        summary=(
            f"{last.probe} -> {last.target} latency {last.duration_ms:.1f}ms "
            f"is {last.duration_ms / p95:.1f}x rolling p95 ({p95:.1f}ms)"
        ),
        details={
            "probe": last.probe, "target": last.target,
            "duration_ms": last.duration_ms, "p95_ms": p95,
        },
    )


def detect_stream_stall(w: RollingWindow, last: Result, cfg: StreamStall) -> Event | None:
    if last.probe != "stream":
        return None
    minute = w.recent_for(
        probe="stream", target=last.target, window_s=60.0, now=last.ts,
    )
    total_stalls = sum(int(r.metrics.get("stall_count", 0)) for r in minute)
    if total_stalls < cfg.min_stalls_per_minute:
        return None
    return Event(
        ts_start=minute[0].ts if minute else last.ts,
        ts_end=last.ts,
        kind="stream_stall",
        severity="warn",
        summary=f"{total_stalls} stream stalls on {last.target} in last minute",
        details={"target": last.target, "stalls": total_stalls},
    )


def detect_wifi_drop(w: RollingWindow, last: Result, cfg: WifiDrop) -> Event | None:
    if last.probe != "wifi":
        return None
    recent = w.recent_for(
        probe="wifi", target=last.target, window_s=float(cfg.window_s), now=last.ts,
    )
    rssis = [
        int(r.metrics["rssi_dbm"])
        for r in recent
        if r.ok and r.metrics.get("rssi_dbm") is not None
    ]
    if len(rssis) < 2:
        return None
    delta = max(rssis) - min(rssis)
    if delta < cfg.delta_dbm:
        return None
    return Event(
        ts_start=recent[0].ts if recent else last.ts,
        ts_end=last.ts,
        kind="wifi_drop",
        severity="info",
        summary=(
            f"wifi RSSI varied by {delta} dBm on {last.target} "
            f"in {cfg.window_s}s (max={max(rssis)} min={min(rssis)})"
        ),
        details={
            "target": last.target, "delta_dbm": delta,
            "max_dbm": max(rssis), "min_dbm": min(rssis),
        },
    )


def detect_mtu_change(w: RollingWindow, last: Result, cfg: MtuChange) -> Event | None:
    if last.probe != "mtu":
        return None
    cur = last.metrics.get("mtu")
    if cur is None:
        return None
    recent = w.recent_for(probe="mtu", target=last.target, now=last.ts)
    # Find the most recent prior result with an mtu metric.
    prev_mtu: int | None = None
    for r in reversed(recent[:-1]):
        v = r.metrics.get("mtu")
        if v is not None:
            prev_mtu = int(v)
            break
    if prev_mtu is None:
        return None
    cur_int = int(cur)
    if cur_int >= prev_mtu:
        return None
    return Event(
        ts_start=last.ts,
        ts_end=last.ts,
        kind="mtu_change",
        severity="warn",
        summary=(
            f"working MTU on {last.target} dropped from {prev_mtu} to {cur_int}"
        ),
        details={
            "target": last.target, "prev_mtu": prev_mtu, "mtu": cur_int,
        },
    )
