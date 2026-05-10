"""Event dataclass — pattern-detector findings."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Severity = Literal["info", "warn", "critical"]


@dataclass(slots=True)
class Event:
    ts_start: datetime
    ts_end: datetime
    kind: str
    severity: Severity
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> tuple[int, int, str, str, str, str | None]:
        return (
            int(self.ts_start.timestamp() * 1000),
            int(self.ts_end.timestamp() * 1000),
            self.kind,
            self.severity,
            self.summary,
            json.dumps(self.details, separators=(",", ":")) if self.details else None,
        )
