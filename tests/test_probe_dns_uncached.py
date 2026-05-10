import asyncio
from unittest.mock import AsyncMock, patch

import dns.message
import dns.rdatatype

from nettest.probes.base import ProbeContext
from nettest.probes.dns_uncached import DnsUncachedProbe
from nettest.types import Target


async def test_dns_uncached_uses_unique_subdomain_per_call():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=2000)
    probe = DnsUncachedProbe(ctx, base_domain="dnscheck.example.com")
    target = Target(kind="dns", host="ignored.dnscheck.example.com", resolver="1.1.1.1")

    seen_qnames: list[str] = []

    async def capture(query, *args, **kwargs):
        seen_qnames.append(str(query.question[0].name).rstrip("."))
        return dns.message.make_response(query)

    with patch(
        "nettest.probes.dns_uncached.dns.asyncquery.udp",
        new=AsyncMock(side_effect=capture),
    ):
        await probe.run(target, cancel=asyncio.Event())
        await probe.run(target, cancel=asyncio.Event())
    assert len(seen_qnames) == 2
    assert seen_qnames[0] != seen_qnames[1]
    for q in seen_qnames:
        assert q.endswith(".dnscheck.example.com")
