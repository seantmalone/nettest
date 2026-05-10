"""Cross-platform autodetection of default gateway and system DNS resolvers."""
from __future__ import annotations

import ipaddress
import platform
import re
import subprocess


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout


def default_gateway() -> str | None:
    system = platform.system()
    if system == "Darwin":
        rc, out = _run(["route", "-n", "get", "default"])
        if rc == 0:
            m = re.search(r"gateway:\s*([0-9.]+)", out)
            if m:
                return m.group(1)
        # Fallback: when the default route is via a tunnel interface (e.g.
        # Tailscale's utun*), `route -n get default` returns the interface
        # but no `gateway:` line. Scan netstat for the first non-tunnel
        # default route with a real IPv4 gateway.
        rc, out = _run(["netstat", "-rn", "-f", "inet"])
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] == "default":
                    gw, iface = parts[1], parts[-1]
                    if iface.startswith(("utun", "ipsec")):
                        continue
                    try:
                        ipaddress.ip_address(gw)
                    except ValueError:
                        continue
                    return gw
        return None
    if system == "Linux":
        rc, out = _run(["ip", "route", "show", "default"])
        if rc != 0:
            return None
        m = re.search(r"default via ([0-9.]+)", out)
        return m.group(1) if m else None
    if system == "Windows":
        rc, out = _run(["route", "print", "0.0.0.0"])
        if rc != 0:
            return None
        m = re.search(r"0\.0\.0\.0/0\s+([0-9.]+)", out) or re.search(
            r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+([0-9.]+)", out, re.M
        )
        return m.group(1) if m else None
    return None


def system_dns_resolvers() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        rc, out = _run(["scutil", "--dns"])
        if rc != 0:
            return []
        seen: list[str] = []
        for m in re.finditer(r"nameserver\[\d+\]\s*:\s*([0-9a-fA-F:.]+)", out):
            ip = m.group(1)
            if ip not in seen:
                seen.append(ip)
        return seen
    if system == "Linux":
        try:
            with open("/etc/resolv.conf", encoding="utf-8") as f:
                return [
                    line.split()[1]
                    for line in f
                    if line.startswith("nameserver") and len(line.split()) >= 2
                ]
        except OSError:
            return []
    if system == "Windows":
        rc, out = _run(["powershell", "-NoProfile", "-Command",
                       "(Get-DnsClientServerAddress -AddressFamily IPv4).ServerAddresses"])
        if rc != 0:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]
    return []
