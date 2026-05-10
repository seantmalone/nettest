"""ICMP ping probe via icmplib (unprivileged where supported)."""
from __future__ import annotations

from datetime import UTC, datetime

from icmplib import async_ping

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


class PingProbe(Probe):
    name = "ping"

    def __init__(self, ctx: ProbeContext, packet_size: int = 56):
        super().__init__(ctx)
        self.packet_size = packet_size

    async def measure(self, target: Target) -> Result:
        host = await async_ping(
            target.host,
            count=1,
            interval=0.001,
            timeout=self.ctx.timeout_ms / 1000,
            payload_size=self.packet_size,
            privileged=False,
        )
        ts = datetime.now(UTC)
        if not host.is_alive:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=self.ctx.timeout_ms,
                error="unreachable",
                metrics={"packet_loss": host.packet_loss},
            )
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=True,
            duration_ms=host.avg_rtt,
            metrics={"packet_loss": host.packet_loss},
        )
