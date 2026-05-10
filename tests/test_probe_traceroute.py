import asyncio
from unittest.mock import patch

from nettest.probes.base import ProbeContext
from nettest.probes.traceroute import (
    TracerouteProbe,
    parse_traceroute_output,
    parse_tracert_output,
)
from nettest.types import Target


def test_parse_unix_traceroute():
    out = """\
traceroute to 1.1.1.1 (1.1.1.1), 30 hops max, 60 byte packets
 1  192.168.1.1 (192.168.1.1)  1.234 ms  1.111 ms  1.020 ms
 2  10.0.0.1 (10.0.0.1)  5.0 ms  5.1 ms  *
 3  1.1.1.1 (1.1.1.1)  12.5 ms  12.1 ms  12.7 ms
"""
    hops = parse_traceroute_output(out)
    assert len(hops) == 3
    assert hops[0]["ip"] == "192.168.1.1"
    assert hops[1]["loss_pct"] == round(1 / 3 * 100, 2)
    assert hops[2]["avg_rtt_ms"] is not None


def test_parse_windows_tracert():
    out = """\
Tracing route to 1.1.1.1 over a maximum of 30 hops:

  1     1 ms     1 ms     1 ms  192.168.1.1
  2     5 ms     *        6 ms  10.0.0.1
  3    12 ms    12 ms    13 ms  1.1.1.1

Trace complete.
"""
    hops = parse_tracert_output(out)
    assert len(hops) == 3
    assert hops[1]["loss_pct"] == round(1 / 3 * 100, 2)


async def test_traceroute_probe_invokes_correct_tool():
    ctx = ProbeContext(hostname="h", interval_ms=60000, timeout_ms=5000)
    probe = TracerouteProbe(ctx, max_hops=5)
    sample = "traceroute to 1.1.1.1\n 1  10.0.0.1  1.0 ms  1.0 ms  1.0 ms\n"

    class _Proc:
        returncode = 0

        async def communicate(self):
            return sample.encode(), b""

    async def _fake_exec(*_args, **_kwargs):
        return _Proc()

    with (
        patch("nettest.probes.traceroute.platform.system", return_value="Darwin"),
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
    ):
        res = await probe.run(Target(kind="host", host="1.1.1.1"), cancel=asyncio.Event())
    assert res.ok is True
    assert res.metrics["hops"][0]["ip"] == "10.0.0.1"
