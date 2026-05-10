import asyncio

from nettest.probes.base import ProbeContext
from nettest.probes.tcp_connect import TcpConnectProbe
from nettest.types import Target


async def test_tcp_connect_succeeds_against_local_listener():
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        ctx = ProbeContext(hostname="h", interval_ms=2000, timeout_ms=2000)
        probe = TcpConnectProbe(ctx)
        res = await probe.run(
            Target(kind="tcp", host="127.0.0.1", port=port), cancel=asyncio.Event(),
        )
    finally:
        server.close()
        await server.wait_closed()
    assert res.ok is True
    assert res.duration_ms > 0


async def test_tcp_connect_refused_is_failure():
    ctx = ProbeContext(hostname="h", interval_ms=2000, timeout_ms=500)
    probe = TcpConnectProbe(ctx)
    res = await probe.run(
        Target(kind="tcp", host="127.0.0.1", port=1), cancel=asyncio.Event(),
    )
    assert res.ok is False
    assert res.error is not None
