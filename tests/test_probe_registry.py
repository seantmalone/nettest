"""Tests for nettest.probes.registry."""
from __future__ import annotations

from nettest.config import Config
from nettest.probes.registry import build_probes


def test_build_probes_returns_all_default_types() -> None:
    cfg = Config()
    probes = build_probes(cfg, hostname="h", filter_names=None)
    names = {p.name for p in probes.values()}
    assert {
        "ping", "dns_cached", "dns_uncached", "http", "tcp_connect",
        "traceroute", "stream", "mtu", "bandwidth", "wifi",
    }.issubset(names)


def test_build_probes_filter_subset() -> None:
    cfg = Config()
    probes = build_probes(cfg, hostname="h", filter_names=["ping", "dns_cached"])
    assert set(probes.keys()) == {"ping", "dns_cached"}
