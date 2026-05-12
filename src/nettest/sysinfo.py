"""One-shot system network info: default route, local IP, public IP, Wi-Fi SSID.

Used to populate the UI banner. Separate from probes so it can run once at
startup (and refresh periodically) without showing up in the probe results
stream / health rollups.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import platform
import re
import socket
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from nettest.probes.wifi import (
    _iw_dev_interfaces,
    is_wifi_likely_available,
    parse_airport_output,
    parse_iw_output,
    parse_netsh_output,
    parse_system_profiler_output,
)

_AIRPORT_PATH = (
    "/System/Library/PrivateFrameworks/Apple80211.framework/"
    "Versions/Current/Resources/airport"
)

# State fields let the UI distinguish "we haven't looked yet" (loading) from
# "we looked and the data isn't available" (off/unavailable) from "we have
# a real value". An em-dash alone hides that distinction.
WifiState = Literal["loading", "off", "not_connected", "connected", "unavailable"]
PublicIpState = Literal["loading", "available", "unavailable"]


@dataclass(slots=True)
class SysInfo:
    wifi_ssid: str | None = None
    wifi_bssid: str | None = None
    wifi_signal_dbm: int | None = None
    wifi_state: WifiState = "loading"
    default_iface: str | None = None
    default_gateway: str | None = None
    local_ip: str | None = None
    public_ip: str | None = None
    public_ip_state: PublicIpState = "loading"

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)

    def wifi_label(self) -> str | None:
        """Human-readable identifier for the Wi-Fi association.

        macOS 14+ redacts SSID (and now BSSID) without Location Services
        permission. The literal "<redacted>" still tells us a Wi-Fi
        association exists — surface that so the user understands the
        gap is a permission issue, not a missing connection.
        """
        if self.wifi_ssid and self.wifi_ssid != "<redacted>":
            return self.wifi_ssid
        if self.wifi_bssid:
            return f"(hidden) {self.wifi_bssid}"
        if self.wifi_ssid == "<redacted>" or self.wifi_signal_dbm is not None:
            return "(SSID hidden by macOS)"
        return None


async def _run(cmd: list[str], timeout_s: float = 3.0) -> tuple[int, str]:
    """Run a command and capture stdout. Returns (-1, '') if the binary is missing."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return -1, ""
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        return -1, ""
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, stdout.decode("utf-8", errors="replace")


async def default_route() -> tuple[str | None, str | None]:
    """Return (interface, gateway_ip) for the default route, or (None, None)."""
    sysname = platform.system()
    if sysname == "Darwin":
        rc, out = await _run(["route", "-n", "get", "default"])
        gw: str | None = None
        iface: str | None = None
        if rc == 0:
            m = re.search(r"gateway:\s*([0-9.]+)", out)
            if m:
                gw = m.group(1)
            m = re.search(r"interface:\s*(\S+)", out)
            if m:
                iface = m.group(1)
        # If the chosen default is a tunnel (utun*/ipsec*) and exposes no
        # gateway IP, fall back to netstat's first non-tunnel default route.
        if gw is None or (iface and iface.startswith(("utun", "ipsec"))):
            rc2, out2 = await _run(["netstat", "-rn", "-f", "inet"])
            if rc2 == 0:
                for line in out2.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == "default":
                        cand_gw, cand_iface = parts[1], parts[-1]
                        if cand_iface.startswith(("utun", "ipsec")):
                            continue
                        try:
                            ipaddress.ip_address(cand_gw)
                        except ValueError:
                            continue
                        return cand_iface, cand_gw
        return iface, gw
    if sysname == "Linux":
        rc, out = await _run(["ip", "route", "show", "default"])
        if rc != 0:
            return None, None
        gw = None
        iface = None
        m = re.search(r"default via ([0-9.]+)", out)
        if m:
            gw = m.group(1)
        m = re.search(r"\bdev\s+(\S+)", out)
        if m:
            iface = m.group(1)
        return iface, gw
    if sysname == "Windows":
        rc, out = await _run(["route", "print", "0.0.0.0"])
        if rc != 0:
            return None, None
        m = re.search(
            r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+([0-9.]+)\s+([0-9.]+)", out, re.M,
        )
        if m:
            return m.group(2), m.group(1)
        return None, None
    return None, None


async def local_ip_for_iface(iface: str | None) -> str | None:
    """Return the primary IPv4 address bound to the named interface."""
    if not iface:
        return None
    sysname = platform.system()
    if sysname == "Darwin":
        rc, out = await _run(["ipconfig", "getifaddr", iface])
        if rc == 0:
            ip = out.strip()
            return ip or None
        return None
    if sysname == "Linux":
        rc, out = await _run(["ip", "-4", "-o", "addr", "show", "dev", iface])
        if rc != 0:
            return None
        m = re.search(r"inet\s+([0-9.]+)/", out)
        return m.group(1) if m else None
    if sysname == "Windows":
        # Fallback: enumerate via socket. Not perfect on multi-homed boxes.
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    return None


async def public_ip(timeout_s: float = 3.0) -> str | None:
    """Best-effort public IP lookup. Tries a couple of plain-text endpoints."""
    urls = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://checkip.amazonaws.com",
    ]
    timeout = httpx.Timeout(timeout_s)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = await client.get(url, headers={"User-Agent": "curl/8"})
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            ip = resp.text.strip()
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                continue
            return ip
    return None


async def wifi_info() -> tuple[str | None, str | None, int | None]:
    """Return (ssid, bssid, rssi_dbm) for the current Wi-Fi association.

    SSID may be literally "<redacted>" on macOS 14+ (Apple gates SSID
    behind Location Services); BSSID is still available and identifies
    the AP unambiguously, so we return both.
    """
    sysname = platform.system()
    info: dict[str, object] = {}
    if sysname == "Darwin":
        if os.path.exists(_AIRPORT_PATH):
            rc, out = await _run([_AIRPORT_PATH, "-I"])
            if rc == 0:
                info = parse_airport_output(out)
        if "ssid" not in info or info.get("rssi_dbm") is None:
            rc2, out2 = await _run(["system_profiler", "SPAirPortDataType"], timeout_s=5.0)
            if rc2 == 0:
                sp = parse_system_profiler_output(out2)
                if sp:
                    info = sp
    elif sysname == "Linux":
        rc, out = await _run(["iw", "dev"])
        if rc == 0:
            for iface in _iw_dev_interfaces(out):
                rc2, out2 = await _run(["iw", "dev", iface, "link"])
                if rc2 != 0:
                    continue
                parsed = parse_iw_output(out2)
                if parsed.get("ssid"):
                    info = parsed
                    break
    elif sysname == "Windows":
        rc, out = await _run(["netsh", "wlan", "show", "interfaces"])
        if rc == 0:
            info = parse_netsh_output(out)
    ssid = info.get("ssid")
    bssid = info.get("bssid")
    rssi = info.get("rssi_dbm")
    return (
        ssid if isinstance(ssid, str) and ssid else None,
        bssid if isinstance(bssid, str) and bssid else None,
        rssi if isinstance(rssi, int) else None,
    )


class SysInfoCache:
    """Background refresher for SysInfo. Snapshot is safe to read at any time."""

    def __init__(self, refresh_interval_s: float = 60.0):
        self._refresh_interval_s = refresh_interval_s
        self._snapshot = SysInfo()
        self._stop = False

    def snapshot(self) -> SysInfo:
        return self._snapshot

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        while not self._stop:
            try:
                self._snapshot = await gather()
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                # Never let a transient lookup error kill the refresh loop.
                pass
            try:
                await asyncio.sleep(self._refresh_interval_s)
            except asyncio.CancelledError:
                return


async def gather() -> SysInfo:
    """Concurrently gather all sysinfo fields. Best-effort: missing data → None."""
    route_task = asyncio.create_task(default_route())
    public_task = asyncio.create_task(public_ip())
    wifi_task = asyncio.create_task(wifi_info())

    iface, gw = await route_task
    local = await local_ip_for_iface(iface)
    pub = await public_task
    ssid, bssid, rssi = await wifi_task

    wifi_state: WifiState
    if ssid or bssid or rssi is not None:
        wifi_state = "connected"
    elif is_wifi_likely_available():
        # Adapter is present and on, but we couldn't read an association —
        # most commonly because we're not joined to a network right now.
        wifi_state = "not_connected"
    else:
        # No adapter, or adapter is powered off. We can't tell those apart
        # cheaply, so we collapse them under "off".
        wifi_state = "off"

    public_ip_state: PublicIpState = "available" if pub else "unavailable"

    return SysInfo(
        wifi_ssid=ssid,
        wifi_bssid=bssid,
        wifi_signal_dbm=rssi,
        wifi_state=wifi_state,
        default_iface=iface,
        default_gateway=gw,
        local_ip=local,
        public_ip=pub,
        public_ip_state=public_ip_state,
    )
