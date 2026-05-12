"""Detail / History / Events / Help screens, and snapshot writer."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from nettest.events import Event
from nettest.tui.aggregator import TargetAggregator
from nettest.tui.styling import format_ms, sparkline_string


class DetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]

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
    BINDINGS = [("escape", "close", "Close")]

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
    BINDINGS = [("escape", "close", "Close")]

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
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        text = (
            "Keybindings:\n"
            "  q          Quit\n"
            "  p          Pause / Resume probes\n"
            "  d          Detail view (selected row)\n"
            "  e          Events list\n"
            "  h          History\n"
            "  s          Save snapshot\n"
            "  ?          Help (this screen)\n"
            "\n"
            "Esc to close."
        )
        yield Static(text)

    def action_close(self) -> None:
        self.app.pop_screen()


def write_snapshot(
    directory: str,
    hostname: str,
    aggregators: dict[tuple[str, str], TargetAggregator],
    events: list[Event],
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
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"snapshot-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path = out_dir / fname
    path.write_text(json.dumps(payload, indent=2, default=str))
    return str(path)


def _snap_to_dict(agg: TargetAggregator) -> dict[str, Any]:
    s = agg.snapshot()
    return {
        "count": s.count, "last_ms": s.last_ms,
        "p50_ms": s.p50_ms, "p95_ms": s.p95_ms, "p99_ms": s.p99_ms,
        "min_ms": s.min_ms, "max_ms": s.max_ms,
        "loss_pct": s.loss_pct, "last_ok": s.last_ok,
        "sparkline": s.sparkline,
    }
