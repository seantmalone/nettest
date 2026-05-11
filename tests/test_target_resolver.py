from unittest.mock import patch

from nettest.config import Config
from nettest.target_resolver import resolve_targets


def test_resolve_replaces_auto_gateway():
    cfg = Config()
    with (
        patch("nettest.target_resolver.default_gateway", return_value="192.168.1.1"),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=["192.168.1.1"]),
        patch(
            "nettest.target_resolver.prune_unreachable_resolvers",
            side_effect=lambda rs, timeout_s=2.0: rs,
        ),
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
        patch(
            "nettest.target_resolver.prune_unreachable_resolvers",
            side_effect=lambda rs, timeout_s=2.0: rs,
        ),
    ):
        resolved = resolve_targets(cfg)
    assert all(t.host != "auto:gateway" for t in resolved.ping)


def test_resolve_dns_includes_cached_and_uncached_targets():
    cfg = Config()
    with (
        patch("nettest.target_resolver.default_gateway", return_value=None),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=["8.8.4.4"]),
        patch(
            "nettest.target_resolver.prune_unreachable_resolvers",
            side_effect=lambda rs, timeout_s=2.0: rs,
        ),
    ):
        resolved = resolve_targets(cfg)
    cached_hosts = {(t.resolver, t.host) for t in resolved.dns_cached}
    assert ("8.8.4.4", "google.com") in cached_hosts
    assert ("1.1.1.1", "google.com") in cached_hosts
    # All cached domains are queried against every resolver.
    cached_domains = {t.host for t in resolved.dns_cached}
    assert cached_domains == {
        "google.com", "cloudflare.com", "github.com", "wikipedia.org", "apple.com",
    }
    assert all(t.host == "dnscheck.example.com" for t in resolved.dns_uncached)


def test_resolve_dns_reflects_pruned_subset():
    """Pruning auto-detected resolvers removes them from the resolved targets."""
    cfg = Config()
    # Subset returned by prune: drop "8.8.4.4" (simulating it being unreachable
    # when reported by the OS); static "1.1.1.1" and "8.8.8.8" are kept as-is.
    with (
        patch("nettest.target_resolver.default_gateway", return_value=None),
        patch("nettest.target_resolver.system_dns_resolvers", return_value=["8.8.4.4"]),
        patch(
            "nettest.target_resolver.prune_unreachable_resolvers",
            return_value=[],
        ),
    ):
        resolved = resolve_targets(cfg)
    resolvers = {t.resolver for t in resolved.dns_cached}
    assert "8.8.4.4" not in resolvers
    # Static resolvers from Config defaults stay.
    assert "1.1.1.1" in resolvers
    assert "8.8.8.8" in resolvers


def test_resolve_dns_drops_unreachable_v6_resolver():
    """A simulated unreachable IPv6 resolver from system DNS is dropped."""
    cfg = Config()

    def _prune(rs: list[str], timeout_s: float = 2.0) -> list[str]:
        return [r for r in rs if r == "1.1.1.1"]

    with (
        patch("nettest.target_resolver.default_gateway", return_value=None),
        patch(
            "nettest.target_resolver.system_dns_resolvers",
            return_value=["1.1.1.1", "fd00::dead"],
        ),
        patch("nettest.target_resolver.prune_unreachable_resolvers", side_effect=_prune),
    ):
        resolved = resolve_targets(cfg)
    resolvers = {t.resolver for t in resolved.dns_cached}
    assert "fd00::dead" not in resolvers
    assert "1.1.1.1" in resolvers


def test_static_resolvers_are_not_pruned():
    """Static resolvers must NOT be passed to the pruner."""
    cfg = Config()
    pruner_calls: list[list[str]] = []

    def _prune(rs: list[str], timeout_s: float = 2.0) -> list[str]:
        pruner_calls.append(list(rs))
        return rs

    with (
        patch("nettest.target_resolver.default_gateway", return_value="192.168.1.1"),
        patch(
            "nettest.target_resolver.system_dns_resolvers",
            return_value=["10.0.0.1"],
        ),
        patch("nettest.target_resolver.prune_unreachable_resolvers", side_effect=_prune),
    ):
        resolve_targets(cfg)
    # Default cfg.targets.dns.resolvers = ["auto:system", "1.1.1.1", "8.8.8.8"]
    # The pruner should receive only auto-derived entries.
    assert pruner_calls, "prune_unreachable_resolvers should have been called"
    sent = pruner_calls[0]
    assert "1.1.1.1" not in sent
    assert "8.8.8.8" not in sent
    assert "10.0.0.1" in sent
