"""Expand `auto:` tokens and produce concrete Target lists per probe."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

from nettest.autodetect import default_gateway, system_dns_resolvers
from nettest.config import Config
from nettest.types import Target


@dataclass(slots=True)
class ResolvedTargets:
    ping: list[Target] = field(default_factory=list)
    dns_cached: list[Target] = field(default_factory=list)
    dns_uncached: list[Target] = field(default_factory=list)
    http: list[Target] = field(default_factory=list)
    tcp_connect: list[Target] = field(default_factory=list)
    traceroute: list[Target] = field(default_factory=list)
    stream: list[Target] = field(default_factory=list)
    bandwidth: list[Target] = field(default_factory=list)
    mtu: list[Target] = field(default_factory=list)
    wifi: list[Target] = field(default_factory=list)


def prune_unreachable_resolvers(resolvers: list[str], timeout_s: float = 2.0) -> list[str]:
    """Probe each resolver once; keep only those that respond.

    Used to silently drop OS-advertised resolvers that aren't actually
    reachable from this host (e.g. Tailscale's IPv6 resolvers on a
    network without IPv6 connectivity). Statically-configured resolvers
    are NOT pruned - the user asked for them for a reason.
    """
    import dns.exception
    import dns.message
    import dns.query
    import dns.rdatatype

    alive: list[str] = []
    for r in resolvers:
        try:
            q = dns.message.make_query("cloudflare.com", dns.rdatatype.A)
            dns.query.udp(q, r, timeout=timeout_s)
            alive.append(r)
        except (dns.exception.Timeout, OSError):
            pass
        except Exception:  # noqa: BLE001
            # Network errors, refused, etc. - treat as unreachable.
            pass
    return alive


def _expand_auto_hosts(hosts: list[str]) -> list[str]:
    out: list[str] = []
    for h in hosts:
        if h == "auto:gateway":
            gw = default_gateway()
            if gw:
                out.append(gw)
        elif h == "auto:system":
            out.extend(system_dns_resolvers())
        else:
            out.append(h)
    seen: set[str] = set()
    deduped: list[str] = []
    for h in out:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return deduped


def _resolve_dns_resolvers(entries: list[str]) -> list[str]:
    """Expand auto: tokens for DNS resolvers and prune unreachable auto-detected ones.

    Statically-configured resolvers are passed through untouched. Only
    entries that came from `auto:system` or `auto:gateway` get the
    reachability check, since the user explicitly asked for static ones.
    """
    auto_resolvers: list[str] = []
    static_resolvers: list[str] = []
    for entry in entries:
        if entry == "auto:system":
            auto_resolvers.extend(system_dns_resolvers())
        elif entry == "auto:gateway":
            gw = default_gateway()
            if gw:
                auto_resolvers.append(gw)
        else:
            static_resolvers.append(entry)
    before = list(auto_resolvers)
    auto_resolvers = prune_unreachable_resolvers(auto_resolvers)
    pruned = [r for r in before if r not in auto_resolvers]
    if pruned:
        print(
            f"note: pruned {len(pruned)} unreachable auto-detected "
            f"DNS resolver(s): {pruned}",
            file=sys.stderr,
        )
    seen: set[str] = set()
    resolvers: list[str] = []
    for r in static_resolvers + auto_resolvers:
        if r not in seen:
            seen.add(r)
            resolvers.append(r)
    return resolvers


def resolve_targets(cfg: Config) -> ResolvedTargets:
    rt = ResolvedTargets()

    for h in _expand_auto_hosts(cfg.targets.ping):
        rt.ping.append(Target(kind="host", host=h))
        rt.traceroute.append(Target(kind="host", host=h))

    resolvers = _resolve_dns_resolvers(cfg.targets.dns.resolvers)
    for r in resolvers:
        rt.dns_cached.append(Target(kind="dns", host=cfg.targets.dns.cached_query, resolver=r))
        # DnsUncachedProbe generates a fresh subdomain per call. The Target
        # stores the base domain as a placeholder (used in labels/logs only).
        rt.dns_uncached.append(Target(
            kind="dns",
            host=cfg.targets.dns.uncached_domain,
            resolver=r,
        ))

    for url in cfg.targets.http:
        rt.http.append(Target(kind="url", host=url))

    for tcp in cfg.targets.tcp:
        rt.tcp_connect.append(Target(kind="tcp", host=tcp.host, port=tcp.port))

    rt.stream.append(
        Target(
            kind="stream",
            host=cfg.targets.stream.url,
            extra={"duration_s": cfg.targets.stream.duration_s},
        )
    )

    for url in cfg.targets.http:
        rt.bandwidth.append(Target(kind="url", host=url))

    rt.mtu = [Target(kind="host", host=h) for h in _expand_auto_hosts(cfg.targets.ping)]
    rt.wifi = [Target(kind="host", host="local")]

    return rt
