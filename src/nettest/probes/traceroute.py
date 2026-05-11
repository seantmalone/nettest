"""Traceroute probe using the system tool. Parses output cross-platform."""
from __future__ import annotations

import asyncio
import platform
import re
import time
from datetime import UTC, datetime
from typing import Any

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target

_UNIX_HOP_RE = re.compile(
    r"^\s*(\d+)\s+(?:([\w.-]+)\s+\(([\d.]+)\)|([\d.]+)|(\*))",
)
_TIME_TOKEN_RE = re.compile(r"([\d.]+)\s*ms|\*")
_WIN_HOP_RE = re.compile(
    r"^\s*(\d+)\s+(<?\s*[\d.]+\s*ms|\*)\s+(<?\s*[\d.]+\s*ms|\*)\s+"
    r"(<?\s*[\d.]+\s*ms|\*)\s+(\S+)\s*$",
)


def _hop_stats(times_ms: list[float | None]) -> tuple[float | None, float]:
    valid = [t for t in times_ms if t is not None]
    if not times_ms:
        return None, 0.0
    avg = sum(valid) / len(valid) if valid else None
    loss = (1 - len(valid) / len(times_ms)) * 100
    return avg, round(loss, 2)


def parse_traceroute_output(out: str) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for line in out.splitlines():
        m = _UNIX_HOP_RE.match(line)
        if not m:
            continue
        ip = m.group(3) or m.group(4)
        rtts: list[float | None] = []
        for tok in _TIME_TOKEN_RE.findall(line):
            if tok in ("*", ""):
                rtts.append(None)
            else:
                rtts.append(float(tok))
        rtts = rtts[:3]
        avg, loss = _hop_stats(rtts)
        hops.append({"ip": ip, "avg_rtt_ms": avg, "loss_pct": loss, "rtts": rtts})
    return hops


def parse_tracert_output(out: str) -> list[dict[str, Any]]:
    """Parse Windows `tracert` output."""
    hops: list[dict[str, Any]] = []
    for line in out.splitlines():
        m = _WIN_HOP_RE.match(line)
        if not m:
            continue
        rtts: list[float | None] = []
        for cell_raw in (m.group(2), m.group(3), m.group(4)):
            cell = cell_raw.strip()
            if cell == "*":
                rtts.append(None)
                continue
            num = cell.replace("<", "").replace("ms", "").strip()
            try:
                rtts.append(float(num))
            except ValueError:
                rtts.append(None)
        ip = m.group(5)
        avg, loss = _hop_stats(rtts)
        hops.append({"ip": ip, "avg_rtt_ms": avg, "loss_pct": loss, "rtts": rtts})
    return hops


class TracerouteProbe(Probe):
    name = "traceroute"

    def __init__(self, ctx: ProbeContext, max_hops: int = 30):
        super().__init__(ctx)
        self.max_hops = max_hops

    async def measure(self, target: Target) -> Result:
        if target.kind != "host":
            raise ValueError("traceroute requires Target(kind='host')")
        sysname = platform.system()
        if sysname == "Windows":
            cmd = [
                "tracert", "-d", "-h", str(self.max_hops),
                "-w", str(self.ctx.timeout_ms), target.host,
            ]
            parser = parse_tracert_output
        else:
            # `-w` is per-probe wait, NOT a total budget. Setting it to the
            # full timeout_ms means a single dropped hop will pin the
            # process for `timeout_s` per probe (× 3 probes × 30 hops),
            # which guarantees the outer Probe.run() cancellation fires
            # before traceroute can finish. Keep it small; the outer
            # wrapper governs total runtime.
            cmd = [
                "traceroute", "-n", "-q", "3", "-w", "2",
                "-m", str(self.max_hops), target.host,
            ]
            parser = parse_traceroute_output

        ts = datetime.now(UTC)
        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        elapsed = (time.perf_counter() - t0) * 1000
        if proc.returncode != 0 and not stdout:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=elapsed, error=f"exit {proc.returncode}",
            )
        hops = parser(stdout.decode("utf-8", errors="replace"))
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=bool(hops),
            duration_ms=elapsed,
            metrics={"hops": hops},
        )
