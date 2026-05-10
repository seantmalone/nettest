"""DNS probe using cacheable stable hostname against a specific resolver."""
from __future__ import annotations

import time
from datetime import UTC, datetime

import dns.asyncquery
import dns.message
import dns.rcode
import dns.rdatatype

from nettest.probes.base import Probe
from nettest.types import Result, Target

_RCODE_NAMES = {0: "NOERROR", 2: "SERVFAIL", 3: "NXDOMAIN", 5: "REFUSED"}


class DnsCachedProbe(Probe):
    name = "dns_cached"

    async def measure(self, target: Target) -> Result:
        if target.kind != "dns" or not target.resolver:
            raise ValueError("dns_cached requires Target(kind='dns', resolver=...)")
        query = dns.message.make_query(target.host, dns.rdatatype.A)
        t0 = time.perf_counter()
        resp = await dns.asyncquery.udp(
            query, target.resolver, timeout=self.ctx.timeout_ms / 1000,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        ts = datetime.now(UTC)
        if resp.rcode() != dns.rcode.NOERROR:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=elapsed,
                error=_RCODE_NAMES.get(resp.rcode(), f"RCODE{resp.rcode()}"),
            )
        answers = [rr.to_text() for rrset in resp.answer for rr in rrset]
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=True,
            duration_ms=elapsed,
            metrics={"answers": answers},
        )
