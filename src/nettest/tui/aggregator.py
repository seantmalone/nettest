"""Per-target rolling aggregates: last/p50/p95/loss + sparkline buckets."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nettest.types import Result


@dataclass(slots=True)
class TargetSnapshot:
    last_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    loss_pct: float
    count: int
    sparkline: list[float | None]
    last_ok: bool


class TargetAggregator:
    def __init__(self, window_s: float = 30.0, sparkline_buckets: int = 30):
        self._window = timedelta(seconds=window_s)
        self._buckets = sparkline_buckets
        self._results: deque[Result] = deque()

    def record(self, r: Result) -> None:
        self._results.append(r)

    def _evict(self, now: datetime) -> None:
        cutoff = now - self._window
        while self._results and self._results[0].ts < cutoff:
            self._results.popleft()

    def snapshot(self, now: datetime | None = None) -> TargetSnapshot:
        ref = now or (self._results[-1].ts if self._results else datetime.now(UTC))
        self._evict(ref)
        rs = list(self._results)
        if not rs:
            return TargetSnapshot(
                None, None, None, 0.0, 0, [None] * self._buckets, last_ok=True,
            )
        durations = sorted([r.duration_ms for r in rs if r.ok])
        last = rs[-1]
        loss = (1 - sum(1 for r in rs if r.ok) / len(rs)) * 100
        p50 = _pct(durations, 50)
        p95 = _pct(durations, 95)
        return TargetSnapshot(
            last_ms=last.duration_ms if last.ok else None,
            p50_ms=p50,
            p95_ms=p95,
            loss_pct=round(loss, 2),
            count=len(rs),
            sparkline=self._sparkline(rs, ref),
            last_ok=last.ok,
        )

    def _sparkline(self, rs: list[Result], now: datetime) -> list[float | None]:
        if not rs:
            return [None] * self._buckets
        bucket_s = self._window.total_seconds() / self._buckets
        buckets: list[list[float]] = [[] for _ in range(self._buckets)]
        for r in rs:
            age = (now - r.ts).total_seconds()
            idx = self._buckets - 1 - int(age / bucket_s)
            if 0 <= idx < self._buckets and r.ok:
                buckets[idx].append(r.duration_ms)
        return [sum(b) / len(b) if b else None for b in buckets]


def _pct(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    rank = (p / 100) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
