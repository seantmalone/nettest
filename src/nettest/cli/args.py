"""nettest CLI argument parsing."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass


@dataclass(slots=True)
class ParsedArgs:
    config: str | None
    no_tui: bool
    no_web: bool
    quiet: bool
    duration_s: int | None
    probes: list[str] | None
    bind: str | None
    snapshot: bool
    replay_db: str | None
    ascii: bool
    no_color: bool
    beep_on: str | None


def _duration_to_seconds(s: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([smh]?)", s)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid duration: {s!r}")
    n = int(m.group(1))
    unit = m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def parse_args(argv: list[str]) -> ParsedArgs:
    p = argparse.ArgumentParser(
        prog="nettest",
        description="High-frequency network diagnostic utility",
    )
    p.add_argument("--config", help="path to YAML config file")
    p.add_argument("--no-tui", action="store_true", help="disable terminal UI")
    p.add_argument("--no-web", action="store_true", help="disable web dashboard")
    p.add_argument("--quiet", action="store_true", help="no TUI, no web; logs only")
    p.add_argument(
        "--duration",
        type=_duration_to_seconds,
        help="run for fixed duration (e.g. 30s, 5m, 2h)",
    )
    p.add_argument("--probes", help="comma-separated subset of probe names to run")
    p.add_argument("--bind", help="override web dashboard bind address")
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="run for 30s, print summary, exit",
    )
    p.add_argument(
        "--replay",
        dest="replay_db",
        help="open historic results.db in TUI without probing",
    )
    p.add_argument("--ascii", action="store_true", help="ASCII-only TUI rendering")
    p.add_argument("--no-color", action="store_true", help="disable colors in TUI")
    p.add_argument(
        "--beep-on",
        choices=["none", "warn", "critical"],
        help="beep on event severity",
    )

    ns = p.parse_args(argv)
    return ParsedArgs(
        config=ns.config,
        no_tui=ns.no_tui,
        no_web=ns.no_web,
        quiet=ns.quiet,
        duration_s=ns.duration,
        probes=ns.probes.split(",") if ns.probes else None,
        bind=ns.bind,
        snapshot=ns.snapshot,
        replay_db=ns.replay_db,
        ascii=ns.ascii,
        no_color=ns.no_color,
        beep_on=ns.beep_on,
    )
