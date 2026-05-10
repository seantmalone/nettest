"""--replay mode: open a historic results.db in the TUI without running probes.

**v1 limitation (documented):** the replay TUI currently shows an empty live
view because no probes are running. The intended future enhancement streams
historical rows from the SQLite file back through the same TUI consumer path
(by reading rollups_1m and Result rows in time order and feeding the
EventBroadcast and Bus). For now ``--replay`` is most useful via the web
dashboard's REST endpoints, which read directly from the DB.
"""
from __future__ import annotations

from pathlib import Path

from nettest.bus import ResultBus
from nettest.config import Config
from nettest.tui.app import NettestApp
from nettest.tui.event_broadcast import EventBroadcast


def build_replay_app(db_path: Path) -> NettestApp:
    cfg = Config()
    bus = ResultBus()
    events = EventBroadcast()
    return NettestApp(
        bus=bus,
        cfg=cfg,
        hostname=f"replay:{db_path.name}",
        events=events,
    )
