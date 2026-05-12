"""Detail / History / Help / Snapshot / Filter screens + snapshot writer."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from nettest.events import Event
from nettest.sysinfo import SysInfo
from nettest.tui.aggregator import TargetAggregator
from nettest.tui.styling import format_ms, sparkline_string


class DetailScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, probe: str, target: str, aggregator: TargetAggregator):
        super().__init__()
        self._probe = probe
        self._target = target
        self._agg = aggregator

    def compose(self) -> ComposeResult:
        snap = self._agg.snapshot()
        rows = (
            f"Probe:    {self._probe}",
            f"Target:   {self._target}",
            f"Samples:  {snap.count}",
            f"Last:     {format_ms(snap.last_ms)}",
            (
                f"p50/p95/p99 ms: {format_ms(snap.p50_ms, with_unit=False)}"
                f" / {format_ms(snap.p95_ms, with_unit=False)}"
                f" / {format_ms(snap.p99_ms, with_unit=False)}"
            ),
            (
                f"min/max ms:     {format_ms(snap.min_ms, with_unit=False)}"
                f" / {format_ms(snap.max_ms, with_unit=False)}"
            ),
            f"Loss:     {snap.loss_pct:.2f}%",
            f"Spark:    {sparkline_string(snap.sparkline)}",
            "",
            "Press Esc to close",
        )
        yield Vertical(*[Static(r) for r in rows])

    def action_close(self) -> None:
        self.app.pop_screen()


class EventsScreen(ModalScreen[None]):
    """Standalone events modal — retained for callers that want a full list."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, events: list[Event]):
        super().__init__()
        self._events = events

    def compose(self) -> ComposeResult:
        if not self._events:
            yield Static("No events recorded.\nPress Esc to close.")
            return
        lines = [
            (
                f"{e.ts_end.strftime('%H:%M:%S')}  ({e.severity})  "
                f"{rich_escape(e.kind)}: {rich_escape(e.summary)}"
            )
            for e in self._events
        ]
        lines.append("")
        lines.append("Press Esc to close")
        yield Vertical(*[Static(line) for line in lines])

    def action_close(self) -> None:
        self.app.pop_screen()


class HistoryScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, aggregators: dict[tuple[str, str], TargetAggregator]):
        super().__init__()
        self._aggs = aggregators

    def compose(self) -> ComposeResult:
        table: DataTable[Any] = DataTable()
        table.add_columns("Probe", "Target", "p50 ms", "p95 ms", "Loss%", "Spark (30s)")
        for (probe, target), agg in sorted(self._aggs.items()):
            s = agg.snapshot()
            table.add_row(
                probe, target,
                format_ms(s.p50_ms, with_unit=False),
                format_ms(s.p95_ms, with_unit=False),
                f"{s.loss_pct:.2f}",
                sparkline_string(s.sparkline),
            )
        yield Vertical(Static("History  (Esc to close)"), table)

    def action_close(self) -> None:
        self.app.pop_screen()


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        text = (
            "Keybindings\n"
            "─────────────────────────────────────────────────────────────\n"
            "  q     Quit (stops the TUI and pauses scheduler)\n"
            "  p     Pause / resume probes (table freezes while paused)\n"
            "  d     Detail view for selected row "
            "(p50/p95/p99/min/max + sparkline)\n"
            "  e     Toggle events panel (inline next to the table)\n"
            "  h     History — all probes, full sample window\n"
            "  s     Save JSON snapshot of all aggregates + events\n"
            "  m     Mark a moment — adds an Event(kind=manual)\n"
            "  /     Filter rows by text (probe or target substring)\n"
            "  f     Cycle severity filter: all → warn+critical → critical\n"
            "  [ / ] Sparkline window smaller / larger (30s / 5m / 15m)\n"
            "  ?     This screen\n"
            "\n"
            "Navigation\n"
            "─────────────────────────────────────────────────────────────\n"
            "  ↑/↓ or j/k   Move row cursor\n"
            "  Page Up/Down Page through the table\n"
            "  Home / End   Jump to top / bottom\n"
            "\n"
            "Notes\n"
            "─────────────────────────────────────────────────────────────\n"
            "  • `d` requires a selected row — move the cursor first.\n"
            "  • Filter persists across sessions in ~/.config/nettest/\n"
            "  • `m`/`/` open a prompt; submit with Enter, cancel with Esc.\n"
            "\n"
            "Press Esc to close."
        )
        yield Static(text)

    def action_close(self) -> None:
        self.app.pop_screen()


class SnapshotSavedScreen(ModalScreen[None]):
    """Confirmation modal after a snapshot is written.

    Keeps the path visible until the operator dismisses it — the previous
    transient `notify()` auto-dismissed, leaving them to find the file
    blind. Also offers a clipboard copy so they can paste it into a
    ticket or `scp` command without retyping.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("c", "copy_path", "Copy path"),
        Binding("q", "close", show=False),
    ]

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("Snapshot written"),
            Static(f"  {self._path}"),
            Static(""),
            Static("Press [b]c[/b] to copy path, [b]Esc[/b] to dismiss."),
        )

    def action_copy_path(self) -> None:
        try:
            self.app.copy_to_clipboard(self._path)
            self.app.notify("path copied to clipboard", timeout=2)
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"copy failed: {exc}", severity="warning", timeout=4)

    def action_close(self) -> None:
        self.app.pop_screen()


class _SingleLinePromptScreen(ModalScreen[str | None]):
    """Shared baseline for one-line text prompts (`/`, `m`)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    _title: str = ""
    _placeholder: str = ""

    def __init__(self, initial: str = ""):
        super().__init__()
        self._initial = initial

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self._title),
            Input(value=self._initial, placeholder=self._placeholder, id="prompt_input"),
            Static("[dim]Enter to submit · Esc to cancel[/dim]"),
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class FilterPromptScreen(_SingleLinePromptScreen):
    _title = "Filter rows by text (empty to clear):"
    _placeholder = "probe or target substring"


class MarkPromptScreen(_SingleLinePromptScreen):
    _title = "Mark a moment — short note to insert into the event stream:"
    _placeholder = "e.g. started speedtest"


def write_snapshot(
    directory: str,
    hostname: str,
    aggregators: dict[tuple[str, str], TargetAggregator],
    events: list[Event],
    sysinfo: SysInfo | None = None,
    redact: bool = False,
) -> str:
    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "hostname": hostname,
        "aggregators": [
            {"probe": probe, "target": target, **_snap_to_dict(agg)}
            for (probe, target), agg in sorted(aggregators.items())
        ],
        "events": [
            {
                "ts_start": e.ts_start.isoformat(),
                "ts_end": e.ts_end.isoformat(),
                "kind": e.kind,
                "severity": e.severity,
                "summary": e.summary,
                "details": e.details,
            }
            for e in events
        ],
    }
    if sysinfo is not None:
        payload["sysinfo"] = _sysinfo_to_dict(sysinfo, redact=redact)
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"snapshot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path = out_dir / fname
    path.write_text(json.dumps(payload, indent=2, default=str))
    return str(path)


def _sysinfo_to_dict(info: SysInfo, *, redact: bool) -> dict[str, Any]:
    d: dict[str, Any] = dict(info.to_dict())
    if redact:
        # Scrub fields that can identify the user/network when sharing a
        # snapshot externally (ticket attachments, bug reports).
        for key in ("public_ip", "wifi_bssid", "wifi_ssid"):
            if d.get(key):
                d[key] = "<redacted>"
    return d


def _snap_to_dict(agg: TargetAggregator) -> dict[str, Any]:
    s = agg.snapshot()
    return {
        "count": s.count, "last_ms": s.last_ms,
        "p50_ms": s.p50_ms, "p95_ms": s.p95_ms, "p99_ms": s.p99_ms,
        "min_ms": s.min_ms, "max_ms": s.max_ms,
        "loss_pct": s.loss_pct, "last_ok": s.last_ok,
        "sparkline": s.sparkline,
    }
