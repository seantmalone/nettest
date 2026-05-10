"""Scheduler: drives probes at their configured cadence, publishes Results to the bus."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nettest.bus import ResultBus
from nettest.probes.base import Probe
from nettest.types import Result, Target

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Job:
    probe: Probe
    targets: list[Target]
    interval_s: float
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


class Scheduler:
    def __init__(self, bus: ResultBus, hostname: str = "?"):
        self._bus = bus
        self._hostname = hostname
        self._jobs: list[_Job] = []
        self._stopping = asyncio.Event()
        self._paused = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._marker_tasks: set[asyncio.Task[None]] = set()

    @property
    def jobs(self) -> list[_Job]:
        """Public read-only view for tests/diagnostics."""
        return list(self._jobs)

    def add(self, probe: Probe, targets: list[Target]) -> None:
        interval_s = probe.ctx.interval_ms / 1000
        self._jobs.append(_Job(probe=probe, targets=targets, interval_s=interval_s))

    def stop(self) -> None:
        self._stopping.set()
        for j in self._jobs:
            j.cancel.set()

    def pause(self) -> None:
        if not self._paused.is_set():
            self._paused.set()
            for j in self._jobs:
                j.cancel.set()
            self._spawn_marker("_paused")

    def resume(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
            for j in self._jobs:
                j.cancel.clear()
            self._spawn_marker("_resumed")

    def _spawn_marker(self, kind: str) -> None:
        try:
            t = asyncio.create_task(self._emit_marker(kind))
        except RuntimeError:
            return
        self._marker_tasks.add(t)
        t.add_done_callback(self._marker_tasks.discard)

    async def _emit_marker(self, kind: str) -> None:
        r = Result(
            ts=datetime.now(UTC),
            host=self._hostname,
            probe=kind, target="-", ok=True, duration_ms=0,
        )
        await self._bus.publish(r)

    async def run(self) -> None:
        self._tasks = [asyncio.create_task(self._run_job(j)) for j in self._jobs]
        try:
            await self._stopping.wait()
        finally:
            for t in self._tasks:
                t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_job(self, job: _Job) -> None:
        while not self._stopping.is_set():
            if self._paused.is_set():
                await asyncio.sleep(0.05)
                continue
            cycle_start = asyncio.get_event_loop().time()
            for target in job.targets:
                if self._stopping.is_set() or self._paused.is_set():
                    break
                try:
                    res = await job.probe.run(target, job.cancel)
                    await self._bus.publish(res)
                except Exception:
                    log.exception("probe %s crashed", job.probe.name)
            elapsed = asyncio.get_event_loop().time() - cycle_start
            sleep_for = max(0.0, job.interval_s - elapsed)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=sleep_for)
