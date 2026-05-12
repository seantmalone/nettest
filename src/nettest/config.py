"""Pydantic config models with smart defaults + YAML loader."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PositiveInt

_DURATION_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|m|h)?\s*$", re.IGNORECASE)
_DURATION_MULT_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}


def _parse_duration_ms(v: Any) -> int:
    """Accept int (interpreted as ms, for backwards compat) or human duration string.

    Examples: 250 -> 250, "250ms" -> 250, "30s" -> 30000, "5m" -> 300000, "1.5s" -> 1500.
    """
    if isinstance(v, bool):
        # bool is a subclass of int; reject explicitly
        raise TypeError("duration cannot be bool")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        m = _DURATION_RE.match(v)
        if not m:
            raise ValueError(f"invalid duration: {v!r}")
        n = float(m.group(1))
        unit = (m.group(2) or "ms").lower()
        return int(n * _DURATION_MULT_MS[unit])
    raise TypeError(f"duration must be int or str, got {type(v).__name__}")


PositiveDurationMs = Annotated[int, BeforeValidator(_parse_duration_ms), Field(gt=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProbeTimings(_Strict):
    interval_ms: PositiveDurationMs
    timeout_ms: PositiveDurationMs = 1000


class PingProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 250
    timeout_ms: PositiveDurationMs = 1000
    packet_size: PositiveInt = 56


class DnsProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 250
    timeout_ms: PositiveDurationMs = 2000


class HttpProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 2000
    timeout_ms: PositiveDurationMs = 5000


class TcpConnectProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 2000
    timeout_ms: PositiveDurationMs = 3000


class TracerouteProbe(ProbeTimings):
    # Real-world traceroute over 30 hops with `-q 3 -w 1` averages ~10-30s.
    # 45s budget gives headroom without hanging too long when a hop drops.
    interval_ms: PositiveDurationMs = 60_000
    timeout_ms: PositiveDurationMs = 45_000
    max_hops: PositiveInt = 30


class StreamProbe(_Strict):
    restart_interval_ms: PositiveDurationMs = 60_000
    stall_threshold_ms: PositiveDurationMs = 200


class BandwidthProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 300_000
    timeout_ms: PositiveDurationMs = 30_000


class MtuProbe(ProbeTimings):
    interval_ms: PositiveDurationMs = 300_000
    # Budget = (sizes × per-iter ping wait) + slack. With 6 default sizes
    # and a 1s per-iter cap inside _ping_df, we need at least 6s total
    # before Probe.run() cancels with "timeout".
    timeout_ms: PositiveDurationMs = 6000
    sizes: list[int] = Field(default_factory=lambda: [1500, 1472, 1400, 1200, 1000, 576])


class WifiProbe(ProbeTimings):
    # 1s/1s was guaranteed-flaky on macOS 14+: `airport` is gone, and the
    # `system_profiler SPAirPortDataType` fallback typically takes 2-3s.
    # Wi-Fi state also doesn't change second-to-second, so the higher
    # interval keeps the probe useful without thrashing system_profiler.
    interval_ms: PositiveDurationMs = 5000
    timeout_ms: PositiveDurationMs = 5000
    enabled: bool = True


class Probes(_Strict):
    ping: PingProbe = Field(default_factory=PingProbe)
    dns_cached: DnsProbe = Field(default_factory=DnsProbe)
    dns_uncached: DnsProbe = Field(default_factory=DnsProbe)
    http: HttpProbe = Field(default_factory=HttpProbe)
    tcp_connect: TcpConnectProbe = Field(default_factory=TcpConnectProbe)
    traceroute: TracerouteProbe = Field(default_factory=TracerouteProbe)
    stream: StreamProbe = Field(default_factory=StreamProbe)
    bandwidth: BandwidthProbe = Field(default_factory=BandwidthProbe)
    mtu: MtuProbe = Field(default_factory=MtuProbe)
    wifi: WifiProbe = Field(default_factory=WifiProbe)


def _coerce_str_list(v: Any) -> list[str]:
    """Accept a single string or a list of strings; always return a list."""
    if isinstance(v, str):
        return [v]
    return cast(list[str], v)


CachedQueryList = Annotated[list[str], BeforeValidator(_coerce_str_list)]


class DnsTargets(_Strict):
    resolvers: list[str] = Field(default_factory=lambda: ["auto:system", "1.1.1.1", "8.8.8.8"])
    cached_query: CachedQueryList = Field(
        default_factory=lambda: [
            "google.com",
            "cloudflare.com",
            "github.com",
            "wikipedia.org",
            "apple.com",
        ]
    )
    uncached_domain: str = "dnscheck.example.com"


class TcpTarget(_Strict):
    host: str
    port: PositiveInt


class StreamTarget(_Strict):
    # Default to a non-rate-limited speed-test endpoint. Cloudflare's
    # speed.cloudflare.com/__down rate-limits non-browser User-Agents and
    # intermittently 403s repeated requests from the same IP, which makes
    # the stream probe show 100% loss in legitimate runs. Linode's
    # speedtest endpoints don't gate on UA. Override in config if a
    # different geographically-closer endpoint is preferred.
    url: str = "https://speedtest.london.linode.com/100MB-london.bin"
    duration_s: PositiveInt = 10


class Targets(_Strict):
    ping: list[str] = Field(
        default_factory=lambda: ["auto:gateway", "1.1.1.1", "8.8.8.8", "9.9.9.9"]
    )
    dns: DnsTargets = Field(default_factory=DnsTargets)
    http: list[str] = Field(default_factory=lambda: [
        "https://www.google.com",
        "https://www.cloudflare.com",
        # github.com (no www) returns 200 directly; www.github.com 301s,
        # which the HTTP probe (follow_redirects=False) counts as a fail.
        "https://github.com",
        "https://www.wikipedia.org",
        "https://www.apple.com",
    ])
    tcp: list[TcpTarget] = Field(default_factory=list)
    stream: StreamTarget = Field(default_factory=StreamTarget)


class MicroOutage(_Strict):
    min_consecutive_fails: PositiveInt = 3
    window_ms: PositiveDurationMs = 2000


class CorrelatedLoss(_Strict):
    min_targets: PositiveInt = 3
    window_ms: PositiveDurationMs = 1500


class LatencySpike(_Strict):
    p95_multiplier: float = 5.0
    min_samples: PositiveInt = 30


class DnsOnlyFail(_Strict):
    min_dns_fails: PositiveInt = 2
    max_other_fails: int = 0
    window_ms: PositiveDurationMs = 2000


class StreamStall(_Strict):
    min_stalls_per_minute: PositiveInt = 2


class WifiDrop(_Strict):
    delta_dbm: PositiveInt = 10
    window_s: PositiveInt = 5


class MtuChange(_Strict):
    pass


class Patterns(_Strict):
    micro_outage: MicroOutage = Field(default_factory=MicroOutage)
    correlated_loss: CorrelatedLoss = Field(default_factory=CorrelatedLoss)
    latency_spike: LatencySpike = Field(default_factory=LatencySpike)
    dns_only_fail: DnsOnlyFail = Field(default_factory=DnsOnlyFail)
    stream_stall: StreamStall = Field(default_factory=StreamStall)
    wifi_drop: WifiDrop = Field(default_factory=WifiDrop)
    mtu_change: MtuChange = Field(default_factory=MtuChange)
    cooldown_ms: PositiveDurationMs = 5000  # min gap between same-scope event emissions


class TuiUi(_Strict):
    enabled: bool = True
    theme: str = "dark"
    beep_on: str = "none"
    no_color: bool = False
    ascii: bool = False
    # Scrub identifying fields (public IP, BSSID, SSID) from saved snapshots.
    # Useful when attaching a snapshot to a bug report or ticket.
    snapshot_redact: bool = False


class WebUi(_Strict):
    enabled: bool = True
    bind: str = "0.0.0.0"
    port: PositiveInt = 8080


class Ui(_Strict):
    tui: TuiUi = Field(default_factory=TuiUi)
    web: WebUi = Field(default_factory=WebUi)


class Retention(_Strict):
    raw_results_days: int = 7
    rollups_1m_days: int = 90
    rollups_1h_days: int = 365
    events_days: int = -1  # -1 = forever


class JsonlSink(_Strict):
    enabled: bool = True
    rotate: str = "daily"


class SqliteSink(_Strict):
    enabled: bool = True
    file: str = "results.db"


class Storage(_Strict):
    data_dir: str = "./data"
    retention: Retention = Field(default_factory=Retention)
    jsonl: JsonlSink = Field(default_factory=JsonlSink)
    sqlite: SqliteSink = Field(default_factory=SqliteSink)


class ProbeThreshold(_Strict):
    warn_loss_pct: float = 1
    crit_loss_pct: float = 5
    warn_p95_ms: float = 100
    crit_p95_ms: float = 500


class Thresholds(_Strict):
    ping: ProbeThreshold = Field(
        default_factory=lambda: ProbeThreshold(warn_p95_ms=50, crit_p95_ms=200)
    )
    dns_cached: ProbeThreshold = Field(
        default_factory=lambda: ProbeThreshold(warn_p95_ms=30, crit_p95_ms=150)
    )
    dns_uncached: ProbeThreshold = Field(
        default_factory=lambda: ProbeThreshold(warn_p95_ms=100, crit_p95_ms=500)
    )
    http: ProbeThreshold = Field(
        default_factory=lambda: ProbeThreshold(warn_p95_ms=500, crit_p95_ms=2000)
    )


class Config(_Strict):
    targets: Targets = Field(default_factory=Targets)
    probes: Probes = Field(default_factory=Probes)
    patterns: Patterns = Field(default_factory=Patterns)
    ui: Ui = Field(default_factory=Ui)
    storage: Storage = Field(default_factory=Storage)
    thresholds: Thresholds = Field(default_factory=Thresholds)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def load_config(
    config_path: Path | None = None,
    search_dirs: list[Path] | None = None,
) -> Config:
    if config_path is not None:
        return Config.model_validate(_read_yaml(config_path))
    for d in search_dirs or []:
        candidate = d / "nettest.yaml"
        if candidate.is_file():
            return Config.model_validate(_read_yaml(candidate))
    return Config()
