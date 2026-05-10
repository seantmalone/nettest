"""Bind address sanity checks."""
from __future__ import annotations

import ipaddress
import socket

# RFC 6598 shared address space (CGNAT) — used by carrier networks AND
# Tailscale by default. Python's ipaddress.is_private doesn't include this
# range, so we check it explicitly.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_rfc1918(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    return isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT


def warn_if_public_bind(bind: str, interfaces: list[str]) -> str | None:
    if bind in ("127.0.0.1", "localhost", "::1"):
        return None
    publics = [ip for ip in interfaces if not is_rfc1918(ip)]
    if not publics:
        return None
    return (
        f"WARNING: web dashboard binding to {bind} on interface with public IP(s) "
        f"{', '.join(publics)}. Use --bind 127.0.0.1 to restrict to localhost."
    )


def list_interface_ips() -> list[str]:
    ips: list[str] = []
    try:
        info = socket.getaddrinfo(socket.gethostname(), None)
        for entry in info:
            ip = str(entry[4][0])
            if ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass
    return ips
