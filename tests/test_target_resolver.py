from unittest.mock import patch

from nettest.config import Config
from nettest.target_resolver import resolve_targets


def test_resolve_replaces_auto_gateway():
    cfg = Config()
    with (
        patch("nettest.target_resolver.default_gateway", return_value="192.168.1.1"),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=["192.168.1.1"]),
    ):
        resolved = resolve_targets(cfg)
    ping_hosts = [t.host for t in resolved.ping]
    assert "192.168.1.1" in ping_hosts
    assert "auto:gateway" not in ping_hosts


def test_resolve_drops_auto_gateway_when_unavailable():
    cfg = Config()
    with (
        patch("nettest.target_resolver.default_gateway", return_value=None),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=[]),
    ):
        resolved = resolve_targets(cfg)
    assert all(t.host != "auto:gateway" for t in resolved.ping)


def test_resolve_dns_includes_cached_and_uncached_targets():
    cfg = Config()
    with (
        patch("nettest.target_resolver.default_gateway", return_value=None),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=["8.8.4.4"]),
    ):
        resolved = resolve_targets(cfg)
    cached_hosts = {(t.resolver, t.host) for t in resolved.dns_cached}
    assert ("8.8.4.4", "google.com") in cached_hosts
    assert ("1.1.1.1", "google.com") in cached_hosts
    assert all(t.host == "google.com" for t in resolved.dns_cached)
    assert all(t.host == "dnscheck.example.com" for t in resolved.dns_uncached)
