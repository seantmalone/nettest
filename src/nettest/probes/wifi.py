"""Wi-Fi sampling probe — RSSI, SSID, BSSID, channel, link rate."""
from __future__ import annotations

import asyncio
import platform
import re
import time
from datetime import UTC, datetime
from typing import Any

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


def _to_int(s: str | None) -> int | None:
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_airport_output(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("SSID:"):
            info["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("BSSID:"):
            info["bssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("agrCtlRSSI:"):
            info["rssi_dbm"] = _to_int(line.split(":", 1)[1].strip())
        elif line.startswith("agrCtlNoise:"):
            info["noise_dbm"] = _to_int(line.split(":", 1)[1].strip())
        elif line.startswith("channel:"):
            info["channel"] = line.split(":", 1)[1].strip()
        elif line.startswith("lastTxRate:"):
            info["link_rate_mbps"] = _to_int(line.split(":", 1)[1].strip())
    return info


def parse_netsh_output(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("SSID") and ":" in line and "BSSID" not in line:
            info["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("BSSID"):
            info["bssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("Signal"):
            pct_str = line.split(":", 1)[1].strip().replace("%", "")
            try:
                pct = int(pct_str)
                info["rssi_dbm"] = -100 + (pct // 2)
            except ValueError:
                info["rssi_dbm"] = None
        elif line.startswith("Channel"):
            info["channel"] = line.split(":", 1)[1].strip()
        elif line.startswith(("Receive rate", "Transmit rate")):
            info["link_rate_mbps"] = _to_int(line.split(":", 1)[1].strip())
    return info


def parse_iw_output(out: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if m := re.search(r"Connected to ([0-9a-f:]{17})", out):
        info["bssid"] = m.group(1)
    if m := re.search(r"SSID:\s*(.+)", out):
        info["ssid"] = m.group(1).strip()
    if m := re.search(r"signal:\s*(-?\d+)\s*dBm", out):
        info["rssi_dbm"] = int(m.group(1))
    if m := re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", out):
        info["link_rate_mbps"] = int(float(m.group(1)))
    return info


class WifiProbe(Probe):
    name = "wifi"

    def __init__(self, ctx: ProbeContext, enabled: bool = True):
        super().__init__(ctx)
        self.enabled = enabled

    async def measure(self, target: Target) -> Result:
        ts = datetime.now(UTC)
        if not self.enabled:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=0, error="disabled",
            )
        sysname = platform.system()
        t0 = time.perf_counter()
        if sysname == "Darwin":
            cmd = [
                "/System/Library/PrivateFrameworks/Apple80211.framework/"
                "Versions/Current/Resources/airport",
                "-I",
            ]
            parser = parse_airport_output
        elif sysname == "Windows":
            cmd = ["netsh", "wlan", "show", "interfaces"]
            parser = parse_netsh_output
        elif sysname == "Linux":
            cmd = ["iw", "dev", "wlan0", "link"]
            parser = parse_iw_output
        else:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False, duration_ms=0,
                error=f"unsupported platform {sysname}",
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except FileNotFoundError as e:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=f"tool not found: {e}",
            )
        if proc.returncode != 0:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False,
                duration_ms=(time.perf_counter() - t0) * 1000,
                error=f"exit {proc.returncode}",
            )
        info = parser(stdout.decode("utf-8", errors="replace"))
        ok = "ssid" in info and info.get("rssi_dbm") is not None
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=ok,
            duration_ms=(time.perf_counter() - t0) * 1000,
            error=None if ok else "no wifi info",
            metrics=info,
        )
