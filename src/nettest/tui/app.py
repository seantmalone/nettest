"""Textual TUI app — header, health, targets, events panels."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from rich.markup import escape as rich_escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from nettest.bus import ResultBus
from nettest.config import Config
from nettest.events import Event
from nettest.sysinfo import SysInfo, SysInfoCache
from nettest.tui.aggregator import TargetAggregator
from nettest.tui.event_broadcast import EventBroadcast
from nettest.tui.health import compute_health_summary
from nettest.tui.styling import (
    ASCII_ICONS,
    ICONS,
    SEVERITY_RANK,
    classify_probe,
    format_ms,
    sparkline_string,
)


class _Pausable(Protocol):
    def pause(self) -> None: ...
    def resume(self) -> None: ...


_SEVERITY_DOT = {
    "ok": "[#3ecf8e]●[/]",
    "warn": "[#f5c344]●[/]",
    "critical": "[#e5484d]●[/]",
}

# Event severity (info/warn/critical) -> status severity dot (ok/warn/critical).
_EVENT_SEV_TO_STATUS = {"info": "ok", "warn": "warn", "critical": "critical"}

_SEVERITY_ROW_STYLE = {
    "warn": "yellow",
    "critical": "bold red",
}

_SPARK_WINDOWS_S: tuple[float, ...] = (30.0, 300.0, 900.0)  # 30s / 5m / 15m
_DEFAULT_SPARK_WINDOW_S = 30.0
_RETAIN_S = 900.0  # keep enough raw data to render the longest window

_FILTER_DOTFILE = Path.home() / ".config" / "nettest" / "tui_filter.json"
_SEVERITY_FILTER_CYCLE: tuple[str, ...] = ("all", "warn", "critical")
_SEVERITY_FILTER_HELP = {
    "all": "all",
    "warn": "warn+critical",
    "critical": "critical only",
}


class NettestApp(App[None]):
    CSS = """
    #sysinfo { height: 3; border: solid $accent; padding: 0 1; }
    #health { height: 8; border: solid $accent; padding: 0 1; }
    #targets { border: solid $accent; padding: 0 1; }
    #events  { border: solid $accent; padding: 0 1; display: none; }
    #weblink { height: 1; padding: 0 1; color: $accent; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause/Resume"),
        Binding("d", "drill", "Detail"),
        Binding("e", "toggle_events", "Events"),
        Binding("h", "show_history", "History"),
        Binding("s", "save_snapshot", "Snapshot"),
        Binding("m", "mark", "Mark"),
        Binding("/", "filter_text", "Filter"),
        Binding("f", "cycle_severity_filter", "Severity"),
        Binding("[", "spark_window_smaller", show=False),
        Binding("]", "spark_window_larger", show=False),
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
        sysinfo: SysInfoCache | None = None,
        web_url: str | None = None,
        snapshot_redact: bool = False,
    ):
        super().__init__()
        self._bus = bus
        self._cfg = cfg
        self._hostname = hostname
        self._scheduler = scheduler
        self._event_bus = events
        self._icons = ASCII_ICONS if ascii else ICONS
        self._no_color = no_color
        self._theme_name = theme
        self._snapshot_dir = snapshot_dir
        self._snapshot_redact = snapshot_redact
        self._sysinfo = sysinfo
        self._web_url = web_url
        self.aggregators: dict[tuple[str, str], TargetAggregator] = {}
        self._events: deque[Event] = deque(maxlen=50)
        self._is_quitting = False
        self._paused = False
        self._started_at = datetime.now(UTC)
        self._consume_task: asyncio.Task[None] | None = None
        self._text_filter = ""
        self._severity_filter = "all"
        self._load_filter_state()
        self._spark_window_s = _DEFAULT_SPARK_WINDOW_S
        self._events_visible = False
        events.subscribe(self._on_event)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._render_banner(), id="banner")
        yield Container(Static("gathering system info...", id="sysinfo_text"), id="sysinfo")
        yield Container(Static("loading...", id="health_text"), id="health")
        with Horizontal(id="main"):
            yield DataTable(id="targets")
            yield Container(RichLog(id="events_log", wrap=True, markup=True), id="events")
        if self._web_url:
            yield Static(f"  Web UI: {self._web_url}", id="weblink")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable[Any] = self.query_one("#targets", DataTable)
        table.add_columns("Probe", "Target", "Last", "p50", "p95", "Loss%", "Spark")
        table.cursor_type = "row"
        self._row_keys: dict[tuple[str, str], Any] = {}
        self._consume_task = asyncio.create_task(self._consume())
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
                TargetAggregator(
                    window_s=_DEFAULT_SPARK_WINDOW_S,
                    sparkline_buckets=24,
                    retain_s=_RETAIN_S,
                ),
            )
            agg.record(r)

    def _on_event(self, event: Event) -> None:
        self._events.append(event)
        if not self._is_quitting:
            with contextlib.suppress(Exception):
                self._append_event_log(event)

    def _append_event_log(self, event: Event) -> None:
        try:
            log = self.query_one("#events_log", RichLog)
        except Exception:  # noqa: BLE001
            return
        status_sev = _EVENT_SEV_TO_STATUS.get(event.severity, "warn")
        log.write(
            f"{self._dot(status_sev)}  {event.ts_end.strftime('%H:%M:%S')}  "
            f"{rich_escape(event.kind)}: {rich_escape(event.summary)}"
        )

    def _dot(self, severity: str) -> str:
        if self._no_color:
            return "●"
        return _SEVERITY_DOT.get(severity, "●")

    def _render_banner(self) -> str:
        bits = [f"  nettest · {self._hostname}"]
        if self._paused:
            # Escape the square brackets so Rich renders them literally
            # rather than treating `[PAUSED]` as an unknown style tag.
            bits.append(r"[reverse #f5c344] \[PAUSED] [/]")
        return "  ".join(bits)

    def _wifi_part(self, info: SysInfo) -> str:
        state = info.wifi_state
        if state == "loading":
            return "…"
        if state == "off":
            return "off"
        if state == "not_connected":
            return "not connected"
        if state == "unavailable":
            return "n/a"
        label = info.wifi_label() or "?"
        if info.wifi_signal_dbm is not None:
            return f"{label} ({info.wifi_signal_dbm} dBm)"
        return label

    def _public_ip_part(self, info: SysInfo) -> str:
        state = info.public_ip_state
        if state == "loading":
            return "…"
        if state == "unavailable":
            return "n/a"
        return info.public_ip or "n/a"

    def _format_sysinfo(self, info: SysInfo) -> str:
        def _f(v: object | None) -> str:
            return "—" if v is None or v == "" else str(v)

        return (
            f"  Wi-Fi: {self._wifi_part(info)}    "
            f"Local: {_f(info.local_ip)} via {_f(info.default_iface)} "
            f"→ {_f(info.default_gateway)}    "
            f"Public: {self._public_ip_part(info)}"
        )

    def _refresh(self) -> None:
        if self._sysinfo is not None:
            self.query_one("#sysinfo_text", Static).update(
                self._format_sysinfo(self._sysinfo.snapshot()),
            )

        # When paused, freeze health/table so the operator sees that pause
        # actually took effect — the consume task may still drain queued
        # results into aggregators, but the visible state stops moving.
        if self._paused:
            return

        spark_buckets = self._spark_buckets()
        snaps = {
            k: v.snapshot(window_s=self._spark_window_s, sparkline_buckets=spark_buckets)
            for k, v in self.aggregators.items()
        }
        rows = compute_health_summary(snaps, thresholds=self._cfg.thresholds)
        health_lines = [
            f"  {self._dot(row.severity)}  {row.severity:8}  {row.name:10}  {row.detail}"
            for row in rows
        ]
        self.query_one("#health_text", Static).update("\n".join(health_lines))
        self._render_table(snaps)
        self._update_events_visibility()

    def _spark_buckets(self) -> int:
        """Scale sparkline width to remaining column width.

        Falls back to 24 when the table width isn't measurable yet (first
        paint). Subtracts the width of the fixed-width columns; clamped to
        a sensible range so a very wide table doesn't blow up the deque.
        """
        try:
            table: DataTable[Any] = self.query_one("#targets", DataTable)
            total = table.size.width
        except Exception:  # noqa: BLE001
            return 24
        # rough widths: probe(12) + target(28) + last(6) + p50(6) + p95(6) + loss(8)
        fixed = 12 + 28 + 6 + 6 + 6 + 8 + 7  # +7 borders/padding
        avail = max(8, total - fixed)
        return max(8, min(60, avail))

    def _update_events_visibility(self) -> None:
        try:
            panel = self.query_one("#events", Container)
            table = self.query_one("#targets", DataTable)
        except Exception:  # noqa: BLE001
            return
        if self._events_visible and self._events:
            panel.styles.display = "block"
            panel.styles.width = "45%"
            table.styles.width = "55%"
        else:
            panel.styles.display = "none"
            table.styles.width = "100%"

    def _row_passes_filter(self, probe: str, target: str, severity: str) -> bool:
        if self._severity_filter != "all":
            if self._severity_filter == "warn" and severity == "ok":
                return False
            if self._severity_filter == "critical" and severity != "critical":
                return False
        if self._text_filter:
            needle = self._text_filter.lower()
            if needle not in probe.lower() and needle not in target.lower():
                return False
        return True

    def _render_table(self, snaps: dict[tuple[str, str], Any]) -> None:
        table: DataTable[Any] = self.query_one("#targets", DataTable)
        prepared = []
        for (probe, target), s in snaps.items():
            sev = classify_probe(
                loss_pct=s.loss_pct, p95_ms=s.p95_ms,
                th=getattr(self._cfg.thresholds, probe, self._cfg.thresholds.ping),
            )
            if not self._row_passes_filter(probe, target, sev):
                continue
            prepared.append((probe, target, s, sev))

        # Worst first so the operator's eye lands on `critical` rows
        # without scrolling, then `warn`, then ties broken by p95.
        prepared.sort(
            key=lambda x: (
                -SEVERITY_RANK.get(x[3], 0),
                -(x[2].p95_ms or 0.0),
                x[0], x[1],
            )
        )

        prior_cursor = table.cursor_row
        table.clear()
        self._row_keys.clear()
        for probe, target, s, sev in prepared:
            spark = sparkline_string(s.sparkline)
            last_v = format_ms(s.last_ms)
            p50_v = format_ms(s.p50_ms, with_unit=False)
            p95_v = format_ms(s.p95_ms, with_unit=False)
            row_style = _SEVERITY_ROW_STYLE.get(sev)
            cells = [
                f"{self._icons.get(probe, '?')} {probe}",
                target, last_v, p50_v, p95_v,
                f"{self._dot(sev)} {s.loss_pct:.1f}%",
                spark,
            ]
            if row_style and not self._no_color:
                cells = [f"[{row_style}]{c}[/]" for c in cells]
            row_key = table.add_row(*cells, key=f"{probe}|{target}")
            self._row_keys[(probe, target)] = row_key

        if prepared:
            target_row = min(prior_cursor, len(prepared) - 1)
            with contextlib.suppress(Exception):
                table.move_cursor(row=max(0, target_row))

    async def action_quit(self) -> None:
        self._is_quitting = True
        if self._consume_task is not None and not self._consume_task.done():
            self._consume_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._consume_task
        if self._scheduler is not None:
            with contextlib.suppress(Exception):
                self._scheduler.pause()
        self.exit()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._scheduler is not None:
            if self._paused:
                self._scheduler.pause()
            else:
                self._scheduler.resume()
        with contextlib.suppress(Exception):
            self.query_one("#banner", Static).update(self._render_banner())

    def action_drill(self) -> None:
        from nettest.tui.detail import DetailScreen
        with contextlib.suppress(Exception):
            table: DataTable[Any] = self.query_one("#targets", DataTable)
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if row_key is None:
                return
            probe, target = str(row_key.value).split("|", 1)
            agg = self.aggregators.get((probe, target))
            if agg is not None:
                self.push_screen(DetailScreen(probe=probe, target=target, aggregator=agg))

    def action_toggle_events(self) -> None:
        self._events_visible = not self._events_visible
        self._update_events_visibility()

    def action_show_history(self) -> None:
        from nettest.tui.detail import HistoryScreen
        self.push_screen(HistoryScreen(aggregators=self.aggregators))

    def action_save_snapshot(self) -> None:
        from nettest.tui.detail import SnapshotSavedScreen, write_snapshot
        sysinfo = self._sysinfo.snapshot() if self._sysinfo is not None else None
        path = write_snapshot(
            directory=self._snapshot_dir,
            hostname=self._hostname,
            aggregators=self.aggregators,
            events=list(self._events),
            sysinfo=sysinfo,
            redact=self._snapshot_redact,
        )
        self.push_screen(SnapshotSavedScreen(path))

    def action_mark(self) -> None:
        from nettest.tui.detail import MarkPromptScreen
        self.push_screen(MarkPromptScreen(), callback=self._on_mark_submitted)

    def _on_mark_submitted(self, text: str | None) -> None:
        if not text:
            return
        now = datetime.now(UTC)
        ev = Event(
            ts_start=now, ts_end=now,
            kind="manual", severity="info",
            summary=text.strip()[:200],
        )
        # Publish through the broadcast so both the TUI events log and the
        # web events panel pick it up via the same path as detector events.
        self._event_bus.publish(ev)

    def action_filter_text(self) -> None:
        from nettest.tui.detail import FilterPromptScreen
        self.push_screen(
            FilterPromptScreen(initial=self._text_filter),
            callback=self._on_filter_submitted,
        )

    def _on_filter_submitted(self, text: str | None) -> None:
        # Esc → None means "leave filter alone"; empty submit means clear.
        if text is None:
            return
        self._text_filter = text.strip()
        self._save_filter_state()

    def action_cycle_severity_filter(self) -> None:
        idx = _SEVERITY_FILTER_CYCLE.index(self._severity_filter)
        self._severity_filter = _SEVERITY_FILTER_CYCLE[
            (idx + 1) % len(_SEVERITY_FILTER_CYCLE)
        ]
        self._save_filter_state()
        self.notify(
            f"severity filter: {_SEVERITY_FILTER_HELP[self._severity_filter]}",
            timeout=2,
        )

    def action_spark_window_smaller(self) -> None:
        self._cycle_spark_window(-1)

    def action_spark_window_larger(self) -> None:
        self._cycle_spark_window(1)

    def _cycle_spark_window(self, direction: int) -> None:
        try:
            idx = _SPARK_WINDOWS_S.index(self._spark_window_s)
        except ValueError:
            idx = 0
        new_idx = max(0, min(len(_SPARK_WINDOWS_S) - 1, idx + direction))
        self._spark_window_s = _SPARK_WINDOWS_S[new_idx]
        self.notify(
            f"sparkline window: {self._format_window(self._spark_window_s)}",
            timeout=2,
        )

    @staticmethod
    def _format_window(s: float) -> str:
        if s < 60:
            return f"{int(s)}s"
        if s < 3600:
            return f"{int(s / 60)}m"
        return f"{int(s / 3600)}h"

    def action_show_help(self) -> None:
        from nettest.tui.detail import HelpScreen
        self.push_screen(HelpScreen())

    def _load_filter_state(self) -> None:
        try:
            data = json.loads(_FILTER_DOTFILE.read_text())
        except (OSError, ValueError):
            return
        text = data.get("text", "")
        sev = data.get("severity", "all")
        if isinstance(text, str):
            self._text_filter = text
        if sev in _SEVERITY_FILTER_CYCLE:
            self._severity_filter = sev

    def _save_filter_state(self) -> None:
        try:
            _FILTER_DOTFILE.parent.mkdir(parents=True, exist_ok=True)
            _FILTER_DOTFILE.write_text(
                json.dumps({
                    "text": self._text_filter,
                    "severity": self._severity_filter,
                })
            )
        except OSError:
            # Filter persistence is a nice-to-have; never crash the TUI on
            # a read-only / unwritable home directory.
            pass
