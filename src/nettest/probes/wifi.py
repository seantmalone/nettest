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


def _iw_dev_interfaces(out: str) -> list[str]:
    """Extract wireless interface names from `iw dev` output."""
    return re.findall(r"^\s*Interface\s+(\S+)\s*$", out, re.MULTILINE)


async def _run_cmd(cmd: list[str]) -> tuple[int, str]:
    """Run a command and return (returncode, stdout). returncode=-1 on FileNotFoundError."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return -1, ""
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, stdout.decode("utf-8", errors="replace")


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
            rc, stdout = await _run_cmd(cmd)
            if rc == -1:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="tool not found: airport",
                )
            if rc != 0:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error=f"exit {rc}",
                )
            info = parse_airport_output(stdout)
        elif sysname == "Windows":
            rc, stdout = await _run_cmd(["netsh", "wlan", "show", "interfaces"])
            if rc == -1:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="tool not found: netsh",
                )
            if rc != 0:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error=f"exit {rc}",
                )
            info = parse_netsh_output(stdout)
        elif sysname == "Linux":
            dev_rc, dev_out = await _run_cmd(["iw", "dev"])
            if dev_rc == -1:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="tool not found: iw",
                )
            if dev_rc != 0:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error=f"iw dev exit {dev_rc}",
                )
            ifaces = _iw_dev_interfaces(dev_out)
            if not ifaces:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="no wireless interface",
                )
            info = {}
            for iface in ifaces:
                rc, stdout = await _run_cmd(["iw", "dev", iface, "link"])
                if rc != 0:
                    continue
                parsed = parse_iw_output(stdout)
                if parsed.get("ssid") and parsed.get("rssi_dbm") is not None:
                    info = parsed
                    break
                # Merge partial info, keeping last as a fallback
                info = parsed or info
        else:
            return Result(
                ts=ts, host=self.ctx.hostname, probe=self.name,
                target=target.label(), ok=False, duration_ms=0,
                error=f"unsupported platform {sysname}",
            )
        ok = "ssid" in info and info.get("rssi_dbm") is not None
        return Result(
            ts=ts, host=self.ctx.hostname, probe=self.name,
            target=target.label(), ok=ok,
            duration_ms=(time.perf_counter() - t0) * 1000,
            error=None if ok else "no wifi info",
            metrics=info,
        )
