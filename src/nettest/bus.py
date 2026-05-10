"""In-memory pub/sub fan-out for probe results."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from nettest.types import Result

DropPolicy = Literal["never", "drop_oldest"]


@dataclass(slots=True)
class _Subscription:
    name: str
    queue: asyncio.Queue[Result]
    drop_policy: DropPolicy
    max_depth: int
    drops: int = 0


class ResultBus:
    def __init__(self) -> None:
        self._subs: dict[str, _Subscription] = {}

    def subscribe(
        self,
        name: str,
        drop_policy: DropPolicy = "never",
        max_depth: int = 1000,
    ) -> asyncio.Queue[Result]:
        if name in self._subs:
            raise ValueError(f"subscriber '{name}' already subscribed")
        q: asyncio.Queue[Result] = asyncio.Queue(maxsize=max_depth)
        self._subs[name] = _Subscription(
            name=name, queue=q, drop_policy=drop_policy, max_depth=max_depth,
        )
        return q

    async def publish(self, result: Result) -> None:
        for sub in list(self._subs.values()):
            if sub.drop_policy == "never":
                await sub.queue.put(result)
            else:
                while sub.queue.full():
                    try:
                        sub.queue.get_nowait()
                        sub.drops += 1
                    except asyncio.QueueEmpty:
                        break
                sub.queue.put_nowait(result)

    def unsubscribe(self, name: str) -> None:
        """Remove a subscriber. Silently no-ops if name not present."""
        self._subs.pop(name, None)

    def drop_count(self, name: str) -> int:
        return self._subs[name].drops

    def subscribers(self) -> list[str]:
        return list(self._subs.keys())
