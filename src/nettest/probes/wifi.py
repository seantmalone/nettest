"""Wi-Fi sampling probe — RSSI, SSID, BSSID, channel, link rate."""
from __future__ import annotations

import asyncio
import platform
import re
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

from nettest.probes.base import Probe, ProbeContext
from nettest.types import Result, Target


def is_wifi_likely_available() -> bool:
    """Quick synchronous check used at startup to decide whether to dispatch the wifi probe.

    Returns False when Wi-Fi is clearly off / not present, so the scheduler
    doesn't fire a probe every cycle generating noise. Conservative: returns
    True on uncertainty (Linux without iw installed, etc.) so the probe can
    surface a real error.
    """
    system = platform.system()
    if system == "Darwin":
        try:
            proc = subprocess.run(
                ["networksetup", "-getairportpower", "en0"],
                capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True
        return proc.returncode == 0 and "Off" not in proc.stdout
    if system == "Linux":
        try:
            proc = subprocess.run(
                ["iw", "dev"], capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True
        return proc.returncode == 0 and "Interface " in proc.stdout
    if system == "Windows":
        try:
            proc = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True
        out = proc.stdout.lower()
        return proc.returncode == 0 and "state" in out and "disconnected" not in out
    return False


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


def parse_system_profiler_output(out: str) -> dict[str, Any]:
    """Parse `system_profiler SPAirPortDataType` output.

    The relevant section looks like:

        Current Network Information:
          <SSID>:
            BSSID: aa:bb:cc:dd:ee:ff
            Channel: 36 (5GHz, 80MHz)
            Signal / Noise: -52 dBm / -90 dBm
            Transmit Rate: 866
    """
    info: dict[str, Any] = {}
    lines = out.splitlines()
    # Find the "Current Network Information:" header.
    idx = -1
    for i, raw in enumerate(lines):
        if raw.strip() == "Current Network Information:":
            idx = i
            break
    if idx == -1:
        return info
    header_indent = len(lines[idx]) - len(lines[idx].lstrip())
    # The next non-empty line at a deeper indent is the SSID key (ending in ":").
    ssid_indent = -1
    for j in range(idx + 1, len(lines)):
        raw = lines[j]
        if not raw.strip():
            continue
        cur_indent = len(raw) - len(raw.lstrip())
        if cur_indent <= header_indent:
            break
        stripped = raw.strip()
        if ssid_indent == -1:
            if stripped.endswith(":"):
                info["ssid"] = stripped[:-1].strip()
                ssid_indent = cur_indent
            continue
        # Deeper than SSID indent means key/value pairs for this SSID.
        if cur_indent <= ssid_indent:
            break
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "BSSID":
            info["bssid"] = value
        elif key == "Channel":
            info["channel"] = value
        elif key == "Signal / Noise":
            # e.g. "-52 dBm / -90 dBm"
            parts = [p.strip() for p in value.split("/")]
            if parts:
                m = re.search(r"-?\d+", parts[0])
                if m:
                    info["rssi_dbm"] = int(m.group(0))
            if len(parts) > 1:
                m = re.search(r"-?\d+", parts[1])
                if m:
                    info["noise_dbm"] = int(m.group(0))
        elif key == "Transmit Rate":
            info["link_rate_mbps"] = _to_int(value)
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
            info: dict[str, Any] = {}
            if rc == 0:
                info = parse_airport_output(stdout)
            # macOS Sonoma 14+ removed airport; fall back to system_profiler.
            # `-detailLevel basic` omits the "Current Network Information"
            # section, so use the default (medium) detail level which always
            # includes it when a network is connected.
            if "ssid" not in info or info.get("rssi_dbm") is None:
                sp_rc, sp_out = await _run_cmd(
                    ["system_profiler", "SPAirPortDataType"],
                )
                if sp_rc == 0:
                    sp_info = parse_system_profiler_output(sp_out)
                    if sp_info:
                        info = sp_info
                    elif "Status: Off" in sp_out:
                        return Result(
                            ts=ts, host=self.ctx.hostname, probe=self.name,
                            target=target.label(), ok=False,
                            duration_ms=(time.perf_counter() - t0) * 1000,
                            error="wifi off",
                        )
                    elif "Current Network Information:" not in sp_out:
                        return Result(
                            ts=ts, host=self.ctx.hostname, probe=self.name,
                            target=target.label(), ok=False,
                            duration_ms=(time.perf_counter() - t0) * 1000,
                            error="not connected to wifi",
                        )
            if not info:
                return Result(
                    ts=ts, host=self.ctx.hostname, probe=self.name,
                    target=target.label(), ok=False,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                    error="no wifi tool available",
                )
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
