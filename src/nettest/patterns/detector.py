"""Pattern detector loop — consumes Results from the bus, emits Events via callback."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from nettest.bus import ResultBus
from nettest.config import Patterns
from nettest.events import Event
from nettest.patterns.rules import (
    detect_correlated_loss,
    detect_dns_only_fail,
    detect_latency_spike,
    detect_micro_outage,
    detect_mtu_change,
    detect_stream_stall,
    detect_wifi_drop,
)
from nettest.patterns.window import RollingWindow
from nettest.types import Result


class PatternDetector:
    def __init__(
        self,
        bus: ResultBus,
        cfg: Patterns,
        on_event: Callable[[Event], None] | None = None,
        window_s: float = 30.0,
    ):
        self._queue = bus.subscribe("patterns", drop_policy="never", max_depth=10_000)
        self._cfg = cfg
        self._on_event: Callable[[Event], None] = on_event or (lambda _e: None)
        self._window = RollingWindow(window_s=window_s)
        self._stopping = asyncio.Event()
        self._last_event_keys: dict[tuple[str, str], int] = {}

    def set_on_event(self, callback: Callable[[Event], None]) -> None:
        """Public setter — Chunk 9 wires this to insert_event + result tagging."""
        self._on_event = callback

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        while not self._stopping.is_set() or not self._queue.empty():
            try:
                r = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if r.probe.startswith("_"):
                continue
            self._window.add(r)
            self._window.evict(r.ts)
            for fn, scope in (
                (detect_micro_outage, ("micro_outage", r.target)),
                (detect_correlated_loss, ("correlated_loss", "*")),
                (detect_dns_only_fail, ("dns_only_fail", "*")),
                (detect_latency_spike, ("latency_spike", f"{r.probe}/{r.target}")),
                (detect_stream_stall, ("stream_stall", r.target)),
                (detect_wifi_drop, ("wifi_drop", r.target)),
                (detect_mtu_change, ("mtu_change", r.target)),
            ):
                e = self._dispatch(fn, r, scope)
                if e is not None:
                    if e.kind not in r.tags:
                        r.tags.append(e.kind)
                    with contextlib.suppress(Exception):
                        self._on_event(e)

    def _dispatch(
        self,
        fn: Callable[..., Event | None],
        r: Result,
        scope: tuple[str, str],
    ) -> Event | None:
        key = scope
        now_ms = int(r.ts.timestamp() * 1000)
        last = self._last_event_keys.get(key, 0)
        if now_ms - last < self._cfg.cooldown_ms:
            return None
        cfg_attr: Any = {
            detect_micro_outage: self._cfg.micro_outage,
            detect_correlated_loss: self._cfg.correlated_loss,
            detect_dns_only_fail: self._cfg.dns_only_fail,
            detect_latency_spike: self._cfg.latency_spike,
            detect_stream_stall: self._cfg.stream_stall,
            detect_wifi_drop: self._cfg.wifi_drop,
            detect_mtu_change: self._cfg.mtu_change,
        }[fn]
        e = fn(self._window, r, cfg_attr)
        if e is not None:
            self._last_event_keys[key] = now_ms
        return e
