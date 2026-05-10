"""DNS probe with random unique subdomain to force recursive lookup."""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import dns.asyncquery
import dns.message
import dns.rcode
import dns.rdatatype

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


class DnsUncachedProbe(Probe):
    name = "dns_uncached"

    def __init__(self, ctx: ProbeContext, base_domain: str = "dnscheck.example.com"):
        super().__init__(ctx)
        self._base = base_domain.lstrip(".")

    async def measure(self, target: Target) -> Result:
        if target.kind != "dns" or not target.resolver:
            raise ValueError("dns_uncached requires Target(kind='dns', resolver=...)")
        qname = f"{uuid.uuid4().hex[:12]}.{self._base}"
        query = dns.message.make_query(qname, dns.rdatatype.A)
        t0 = time.perf_counter()
        resp = await dns.asyncquery.udp(
            query, target.resolver, timeout=self.ctx.timeout_ms / 1000,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        ts = datetime.now(UTC)
        ok = resp.rcode() in (dns.rcode.NOERROR, dns.rcode.NXDOMAIN)
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=ok,
            duration_ms=elapsed,
            error=None if ok else f"RCODE{resp.rcode()}",
            metrics={"qname": qname, "rcode": resp.rcode()},
        )
