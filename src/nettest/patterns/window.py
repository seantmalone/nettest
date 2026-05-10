"""In-memory rolling window of Result records for pattern queries."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from nettest.types import Result


class RollingWindow:
    def __init__(self, window_s: float = 30.0):
        self.window = timedelta(seconds=window_s)
        self.results: deque[Result] = deque()

    def add(self, r: Result) -> None:
        self.results.append(r)

    def evict(self, now: datetime) -> None:
        cutoff = now - self.window
        while self.results and self.results[0].ts < cutoff:
            self.results.popleft()

    def recent_for(
        self,
        probe: str | None = None,
        target: str | None = None,
        window_s: float | None = None,
        now: datetime | None = None,
    ) -> list[Result]:
        if not self.results:
            return []
        ref_now = now or self.results[-1].ts
        cutoff = ref_now - timedelta(seconds=window_s) if window_s else ref_now - self.window
        return [
            r for r in self.results
            if r.ts >= cutoff
            and (probe is None or r.probe == probe)
            and (target is None or r.target == target)
        ]
