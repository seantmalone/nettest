import asyncio
from unittest.mock import AsyncMock, patch

import dns.message
import dns.rdatatype
import dns.rrset

from nettest.probes.base import ProbeContext
from nettest.probes.dns_cached import DnsCachedProbe
from nettest.types import Target


def _fake_response(host: str, ip: str = "1.2.3.4"):
    msg = dns.message.make_response(dns.message.make_query(host, dns.rdatatype.A))
    msg.answer.append(dns.rrset.from_text(host + ".", 60, "IN", "A", ip))
    return msg


async def test_dns_cached_success_returns_resolution_time():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=2000)
    probe = DnsCachedProbe(ctx)
    target = Target(kind="dns", host="google.com", resolver="1.1.1.1")
    with patch(
        "nettest.probes.dns_cached.dns.asyncquery.udp",
        new=AsyncMock(return_value=_fake_response("google.com")),
    ):
        res = await probe.run(target, cancel=asyncio.Event())
    assert res.ok is True
    assert res.duration_ms >= 0
    assert any("1.2.3.4" in a for a in res.metrics["answers"])


async def test_dns_cached_nxdomain_returns_failure():
    ctx = ProbeContext(hostname="h", interval_ms=250, timeout_ms=2000)
    probe = DnsCachedProbe(ctx)
    target = Target(kind="dns", host="nope.example", resolver="1.1.1.1")
    bad = dns.message.make_response(dns.message.make_query("nope.example", dns.rdatatype.A))
    bad.set_rcode(3)
    with patch(
        "nettest.probes.dns_cached.dns.asyncquery.udp",
        new=AsyncMock(return_value=bad),
    ):
        res = await probe.run(target, cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "NXDOMAIN"
