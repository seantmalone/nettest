"""Core data types - Result, Target, ProbeConfig, etc."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


ProbeKind = Literal[
    "ping", "dns_cached", "dns_uncached", "http", "tcp_connect",
    "traceroute", "stream", "mtu", "bandwidth", "wifi",
]
TargetKind = Literal["host", "dns", "url", "tcp", "stream"]


@dataclass(slots=True)
class Target:
    kind: TargetKind
    host: str
    port: int | None = None
    resolver: str | None = None  # for DNS targets
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind == "tcp" and self.port is None:
            raise ValueError("tcp target requires a port")
        if self.kind == "dns" and not self.resolver:
            raise ValueError("dns target requires a resolver")

    def label(self) -> str:
        if self.kind == "dns":
            return f"dns:{self.resolver}/{self.host}"
        if self.kind == "tcp":
            return f"tcp:{self.host}:{self.port}"
        return f"{self.kind}:{self.host}"


@dataclass(slots=True)
class Result:
    ts: datetime
    host: str
    probe: str
    target: str
    ok: bool
    duration_ms: float
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.ts.tzinfo.utcoffset(self.ts) != timezone.utc.utcoffset(None):
            raise ValueError("Result.ts must be timezone-aware UTC")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "host": self.host,
            "probe": self.probe,
            "target": self.target,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "metrics": self.metrics,
            "tags": self.tags,
        }
