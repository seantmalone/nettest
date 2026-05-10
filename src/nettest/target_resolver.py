"""Expand `auto:` tokens and produce concrete Target lists per probe."""
from __future__ import annotations

import uuid
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


def resolve_targets(cfg: Config) -> ResolvedTargets:
    rt = ResolvedTargets()

    for h in _expand_auto_hosts(cfg.targets.ping):
        rt.ping.append(Target(kind="host", host=h))
        rt.traceroute.append(Target(kind="host", host=h))

    resolvers = _expand_auto_hosts(cfg.targets.dns.resolvers)
    for r in resolvers:
        rt.dns_cached.append(Target(kind="dns", host=cfg.targets.dns.cached_query, resolver=r))
        unique = f"{uuid.uuid4().hex[:12]}.{cfg.targets.dns.uncached_domain}"
        rt.dns_uncached.append(Target(kind="dns", host=unique, resolver=r))

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
