"""Bind address sanity checks."""
from __future__ import annotations

import ipaddress
import socket


def is_rfc1918(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


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
