"""Per-target rolling aggregates: last/p50/p95/p99/min/max/loss + sparkline buckets."""
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
    p99_ms: float | None
    min_ms: float | None
    max_ms: float | None
    loss_pct: float
    count: int
    sparkline: list[float | None]
    last_ok: bool


class TargetAggregator:
    """Rolling per-target stats.

    `window_s` is the default analytical window. `retain_s` (>= window_s) is
    how long raw results are kept in the deque so callers can request a
    longer window at `snapshot()` time without losing data — used by the
    dynamic sparkline-window keys (`[`/`]`).
    """

    def __init__(
        self,
        window_s: float = 30.0,
        sparkline_buckets: int = 30,
        retain_s: float | None = None,
    ):
        self._window = timedelta(seconds=window_s)
        self._retain = timedelta(seconds=retain_s if retain_s is not None else window_s)
        if self._retain < self._window:
            self._retain = self._window
        self._buckets = sparkline_buckets
        self._results: deque[Result] = deque()

    def record(self, r: Result) -> None:
        self._results.append(r)

    def _evict(self, now: datetime) -> None:
        cutoff = now - self._retain
        while self._results and self._results[0].ts < cutoff:
            self._results.popleft()

    def snapshot(
        self,
        now: datetime | None = None,
        *,
        window_s: float | None = None,
        sparkline_buckets: int | None = None,
    ) -> TargetSnapshot:
        ref = now or (self._results[-1].ts if self._results else datetime.now(UTC))
        self._evict(ref)
        window = (
            timedelta(seconds=window_s) if window_s is not None else self._window
        )
        buckets = sparkline_buckets if sparkline_buckets is not None else self._buckets
        cutoff = ref - window
        rs = [r for r in self._results if r.ts >= cutoff]
        if not rs:
            return TargetSnapshot(
                last_ms=None, p50_ms=None, p95_ms=None, p99_ms=None,
                min_ms=None, max_ms=None, loss_pct=0.0, count=0,
                sparkline=[None] * buckets, last_ok=True,
            )
        durations = sorted([r.duration_ms for r in rs if r.ok])
        last = rs[-1]
        loss = (1 - sum(1 for r in rs if r.ok) / len(rs)) * 100
        p50 = _pct(durations, 50)
        p95 = _pct(durations, 95)
        p99 = _pct(durations, 99)
        min_ms = durations[0] if durations else None
        max_ms = durations[-1] if durations else None
        return TargetSnapshot(
            last_ms=last.duration_ms if last.ok else None,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            min_ms=min_ms,
            max_ms=max_ms,
            loss_pct=round(loss, 2),
            count=len(rs),
            sparkline=self._sparkline(rs, ref, window, buckets),
            last_ok=last.ok,
        )

    def _sparkline(
        self,
        rs: list[Result],
        now: datetime,
        window: timedelta,
        buckets: int,
    ) -> list[float | None]:
        if not rs or buckets <= 0:
            return [None] * buckets
        bucket_s = window.total_seconds() / buckets
        result_buckets: list[list[float]] = [[] for _ in range(buckets)]
        for r in rs:
            age = (now - r.ts).total_seconds()
            idx = buckets - 1 - int(age / bucket_s)
            if 0 <= idx < buckets and r.ok:
                result_buckets[idx].append(r.duration_ms)
        return [sum(b) / len(b) if b else None for b in result_buckets]


def _pct(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    rank = (p / 100) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
