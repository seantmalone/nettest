"""Build probe instances from Config."""
from __future__ import annotations

from nettest.config import Config
from nettest.probes.bandwidth import BandwidthProbe
from nettest.probes.base import Probe, ProbeContext
from nettest.probes.dns_cached import DnsCachedProbe
from nettest.probes.dns_uncached import DnsUncachedProbe
from nettest.probes.http import HttpProbe
from nettest.probes.mtu import MtuProbe
from nettest.probes.ping import PingProbe
from nettest.probes.stream import StreamProbe
from nettest.probes.tcp_connect import TcpConnectProbe
from nettest.probes.traceroute import TracerouteProbe
from nettest.probes.wifi import WifiProbe


def build_probes(
    cfg: Config,
    hostname: str,
    filter_names: list[str] | None,
) -> dict[str, Probe]:
    def ctx(interval_ms: int, timeout_ms: int) -> ProbeContext:
        return ProbeContext(hostname=hostname, interval_ms=interval_ms, timeout_ms=timeout_ms)

    all_probes: dict[str, Probe] = {
        "ping": PingProbe(
            ctx(cfg.probes.ping.interval_ms, cfg.probes.ping.timeout_ms),
            packet_size=cfg.probes.ping.packet_size,
        ),
        "dns_cached": DnsCachedProbe(
            ctx(cfg.probes.dns_cached.interval_ms, cfg.probes.dns_cached.timeout_ms),
        ),
        "dns_uncached": DnsUncachedProbe(
            ctx(cfg.probes.dns_uncached.interval_ms, cfg.probes.dns_uncached.timeout_ms),
            base_domain=cfg.targets.dns.uncached_domain,
        ),
        "http": HttpProbe(
            ctx(cfg.probes.http.interval_ms, cfg.probes.http.timeout_ms),
        ),
        "tcp_connect": TcpConnectProbe(
            ctx(cfg.probes.tcp_connect.interval_ms, cfg.probes.tcp_connect.timeout_ms),
        ),
        "traceroute": TracerouteProbe(
            ctx(cfg.probes.traceroute.interval_ms, cfg.probes.traceroute.timeout_ms),
            max_hops=cfg.probes.traceroute.max_hops,
        ),
        "stream": StreamProbe(
            # Stream's measure() runs for ~duration_s (default 60s); allow ample timeout.
            # The probe also enforces its own httpx read timeout internally.
            ctx(cfg.probes.stream.restart_interval_ms, 90_000),
            stall_threshold_ms=cfg.probes.stream.stall_threshold_ms,
        ),
        "mtu": MtuProbe(
            ctx(cfg.probes.mtu.interval_ms, cfg.probes.mtu.timeout_ms),
            sizes=cfg.probes.mtu.sizes,
        ),
        "bandwidth": BandwidthProbe(
            ctx(cfg.probes.bandwidth.interval_ms, cfg.probes.bandwidth.timeout_ms),
        ),
        "wifi": WifiProbe(
            ctx(cfg.probes.wifi.interval_ms, cfg.probes.wifi.timeout_ms),
            enabled=cfg.probes.wifi.enabled,
        ),
    }
    if filter_names:
        return {k: v for k, v in all_probes.items() if k in filter_names}
    return all_probes
