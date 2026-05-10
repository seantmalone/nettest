"""Textual TUI app — header, health, targets, events panels."""
from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from datetime import UTC, datetime
from typing import Any, Protocol

from rich.markup import escape as rich_escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.coordinate import Coordinate
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

from nettest.bus import ResultBus
from nettest.config import Config
from nettest.events import Event
from nettest.tui.aggregator import TargetAggregator
from nettest.tui.event_broadcast import EventBroadcast
from nettest.tui.health import compute_health_summary
from nettest.tui.styling import ASCII_ICONS, ICONS, classify_probe, sparkline_string


class _Pausable(Protocol):
    def pause(self) -> None: ...
    def resume(self) -> None: ...


_SEVERITY_DOT = {
    "ok": "[#3ecf8e]●[/]",
    "warn": "[#f5c344]●[/]",
    "crit": "[#e5484d]●[/]",
}


class NettestApp(App[None]):
    CSS = """
    #health { height: 8; border: solid $accent; padding: 0 1; }
    #targets { border: solid $accent; padding: 0 1; }
    #events  { border: solid $accent; padding: 0 1; width: 45%; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause/Resume"),
        Binding("d", "drill", "Detail"),
        Binding("e", "show_events", "Events"),
        Binding("h", "show_history", "History"),
        Binding("s", "save_snapshot", "Snapshot"),
        Binding("?", "show_help", "Help"),
    ]

    total_probes = reactive(0)
    total_fails = reactive(0)

    def __init__(
        self,
        bus: ResultBus,
        cfg: Config,
        hostname: str,
        events: EventBroadcast,
        scheduler: _Pausable | None = None,
        ascii: bool = False,
        no_color: bool = False,
        theme: str = "dark",
        snapshot_dir: str = ".",
    ):
        super().__init__()
        self._bus = bus
        self._cfg = cfg
        self._hostname = hostname
        self._scheduler = scheduler
        self._icons = ASCII_ICONS if ascii else ICONS
        self._no_color = no_color
        self._theme_name = theme
        self._snapshot_dir = snapshot_dir
        self.aggregators: dict[tuple[str, str], TargetAggregator] = {}
        self._events: deque[Event] = deque(maxlen=50)
        self._is_quitting = False
        self._paused = False
        self._started_at = datetime.now(UTC)
        events.subscribe(self._on_event)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"  nettest · {self._hostname}", id="banner")
        yield Container(Static("loading...", id="health_text"), id="health")
        with Horizontal():
            yield DataTable(id="targets")
            yield Container(Static("(events)", id="events_text"), id="events")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#targets", DataTable)
        table.add_columns("Probe", "Target", "Last", "p50", "p95", "Loss%", "Spark")
        self._row_keys: dict[tuple[str, str], Any] = {}
        asyncio.create_task(self._consume())
        self.set_interval(0.25, self._refresh)

    async def _consume(self) -> None:
        q = self._bus.subscribe("tui", drop_policy="drop_oldest", max_depth=2000)
        while not self._is_quitting:
            try:
                r = await asyncio.wait_for(q.get(), timeout=0.1)
            except TimeoutError:
                continue
            if r.probe.startswith("_"):
                continue
            self.total_probes += 1
            if not r.ok:
                self.total_fails += 1
            agg = self.aggregators.setdefault(
                (r.probe, r.target),
                TargetAggregator(window_s=30, sparkline_buckets=12),
            )
            agg.record(r)

    def _on_event(self, event: Event) -> None:
        self._events.append(event)

    def _dot(self, severity: str) -> str:
        if self._no_color:
            return "●"
        return _SEVERITY_DOT.get(severity, "●")

    def _refresh(self) -> None:
        snaps = {k: v.snapshot() for k, v in self.aggregators.items()}
        rows = compute_health_summary(snaps, thresholds=self._cfg.thresholds)
        health_lines = [
            f"  {self._dot(row.severity)}  {row.severity:5}  {row.name:10}  {row.detail}"
            for row in rows
        ]
        self.query_one("#health_text", Static).update("\n".join(health_lines))

        table: DataTable[Any] = self.query_one("#targets", DataTable)
        for (probe, target), s in sorted(snaps.items()):
            sev = classify_probe(
                loss_pct=s.loss_pct, p95_ms=s.p95_ms,
                th=getattr(self._cfg.thresholds, probe, self._cfg.thresholds.ping),
            )
            spark = sparkline_string(s.sparkline)
            last_v = "—" if s.last_ms is None else f"{s.last_ms:.1f}ms"
            p50_v = "—" if s.p50_ms is None else f"{s.p50_ms:.1f}"
            p95_v = "—" if s.p95_ms is None else f"{s.p95_ms:.1f}"
            cells = [
                f"{self._icons.get(probe, '?')} {probe}",
                target, last_v, p50_v, p95_v,
                f"{self._dot(sev)} {s.loss_pct:.1f}%",
                spark,
            ]
            key = (probe, target)
            if key in self._row_keys:
                row_key = self._row_keys[key]
                row_idx = table.get_row_index(row_key)
                for col_idx, value in enumerate(cells):
                    table.update_cell_at(Coordinate(row_idx, col_idx), value)
            else:
                row_key = table.add_row(*cells, key=f"{probe}|{target}")
                self._row_keys[key] = row_key

        if self._events:
            ev_text = "\n".join(
                (
                    f"  {self._dot('crit' if e.severity == 'critical' else e.severity)}  "
                    f"{e.ts_end.strftime('%H:%M:%S')}  "
                    f"{rich_escape(e.kind)}: {rich_escape(e.summary)}"
                )
                for e in list(self._events)[-10:]
            )
        else:
            ev_text = "  (no events yet)"
        self.query_one("#events_text", Static).update(ev_text)

    async def action_quit(self) -> None:
        self._is_quitting = True
        self.exit()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._scheduler is None:
            return
        if self._paused:
            self._scheduler.pause()
        else:
            self._scheduler.resume()

    def action_drill(self) -> None:
        from nettest.tui.detail import DetailScreen  # type: ignore[import-not-found]
        with contextlib.suppress(Exception):
            table: DataTable[Any] = self.query_one("#targets", DataTable)
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key is None:
                return
            probe, target = str(row_key.value).split("|", 1)
            agg = self.aggregators.get((probe, target))
            if agg is not None:
                self.push_screen(DetailScreen(probe=probe, target=target, aggregator=agg))

    def action_show_events(self) -> None:
        from nettest.tui.detail import EventsScreen
        self.push_screen(EventsScreen(events=list(self._events)))

    def action_show_history(self) -> None:
        from nettest.tui.detail import HistoryScreen
        self.push_screen(HistoryScreen(aggregators=self.aggregators))

    def action_save_snapshot(self) -> None:
        from nettest.tui.detail import write_snapshot
        path = write_snapshot(
            directory=self._snapshot_dir,
            hostname=self._hostname,
            aggregators=self.aggregators,
            events=list(self._events),
        )
        self.notify(f"snapshot written: {path}")

    def action_show_help(self) -> None:
        from nettest.tui.detail import HelpScreen
        self.push_screen(HelpScreen())
