"""In-process pub/sub for Event objects (decouples detector from TUI)."""
from __future__ import annotations

import contextlib
from collections.abc import Callable

from nettest.events import Event


class EventBroadcast:
    def __init__(self) -> None:
        self._subs: list[Callable[[Event], None]] = []

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subs.append(callback)

    def publish(self, event: Event) -> None:
        for cb in list(self._subs):
            with contextlib.suppress(Exception):
                cb(event)
