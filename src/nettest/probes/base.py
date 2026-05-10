"""Probe base class — wraps measure() with timeout, cancellation, error handling."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from nettest.types import Result, Target


@dataclass(slots=True)
class ProbeContext:
    hostname: str
    interval_ms: int
    timeout_ms: int


class Probe(ABC):
    name: str = ""

    def __init__(self, ctx: ProbeContext):
        if not self.name:
            raise RuntimeError(f"{type(self).__name__} must set class attribute `name`")
        self.ctx = ctx

    @abstractmethod
    async def measure(self, target: Target) -> Result:
        """Run a single measurement. Raise on failure."""

    async def run(self, target: Target, cancel: asyncio.Event) -> Result:
        if cancel.is_set():
            return self._fail(target, "cancelled", duration_ms=0)
        timeout_s = self.ctx.timeout_ms / 1000
        started = datetime.now(UTC)
        try:
            measure_task = asyncio.create_task(self.measure(target))
            cancel_task = asyncio.create_task(cancel.wait())
            done, pending = await asyncio.wait(
                {measure_task, cancel_task},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if cancel_task in done:
                duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
                return self._fail(target, "cancelled", duration_ms=duration_ms)
            if not done:
                duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
                return self._fail(target, "timeout", duration_ms=duration_ms)
            return measure_task.result()
        except Exception as e:  # noqa: BLE001
            duration_ms = (datetime.now(UTC) - started).total_seconds() * 1000
            return self._fail(target, f"{type(e).__name__}: {e}", duration_ms=duration_ms)

    def _fail(self, target: Target, error: str, duration_ms: float) -> Result:
        return Result(
            ts=datetime.now(UTC),
            host=self.ctx.hostname,
            probe=self.name,
            target=target.label(),
            ok=False,
            duration_ms=duration_ms,
            error=error,
        )
