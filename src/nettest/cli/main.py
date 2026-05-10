"""nettest CLI entry point — wires bus, scheduler, sinks, detector, TUI, web."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from nettest.bus import ResultBus
from nettest.cli.args import ParsedArgs, parse_args
from nettest.cli.binding import list_interface_ips, warn_if_public_bind
from nettest.config import Config, load_config
from nettest.events import Event
from nettest.host import current_hostname
from nettest.patterns.detector import PatternDetector
from nettest.probes.registry import build_probes
from nettest.scheduler import Scheduler
from nettest.storage.background import StorageMaintenance
from nettest.storage.event_sink import insert_event
from nettest.storage.jsonl_sink import JsonlSink
from nettest.storage.schema import init_schema
from nettest.storage.sqlite_sink import SqliteSink
from nettest.target_resolver import resolve_targets
from nettest.tui.event_broadcast import EventBroadcast
from nettest.types import Target

log = logging.getLogger("nettest")


@dataclass
class Runtime:
    args: ParsedArgs
    cfg: Config
    bus: ResultBus
    scheduler: Scheduler
    sqlite_sink: SqliteSink
    jsonl_sink: JsonlSink
    detector: PatternDetector
    maintenance: StorageMaintenance
    db_path: Path
    hostname: str
    events: EventBroadcast

    async def run(self) -> None:
        # ensure schema exists
        conn = sqlite3.connect(self.db_path)
        init_schema(conn)
        conn.close()

        event_db_conn = sqlite3.connect(self.db_path)

        def _on_event(e: Event) -> None:
            # 1) persist to events table
            try:
                insert_event(event_db_conn, e)
            except sqlite3.Error:
                log.exception("failed to persist event")
            # 2) re-broadcast to in-process subscribers (e.g., TUI)
            self.events.publish(e)

        # public setter on detector — no private attribute access.
        self.detector.set_on_event(_on_event)

        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(self.scheduler.run(), name="scheduler"),
            asyncio.create_task(self.sqlite_sink.run(), name="sqlite"),
            asyncio.create_task(self.jsonl_sink.run(), name="jsonl"),
            asyncio.create_task(self.detector.run(), name="detector"),
            asyncio.create_task(self.maintenance.run(), name="maintenance"),
        ]
        web_server: uvicorn.Server | None = None
        if not self.args.no_web and not self.args.quiet:
            from nettest.web.app import build_app
            app = build_app(
                db_path=self.db_path,
                hostname=self.hostname,
                bus=self.bus,
                events=self.events,
            )
            uv_cfg = uvicorn.Config(
                app,
                host=self.args.bind or self.cfg.ui.web.bind,
                port=self.cfg.ui.web.port,
                log_level="warning",
            )
            web_server = uvicorn.Server(uv_cfg)
            tasks.append(asyncio.create_task(web_server.serve(), name="web"))

        if not self.args.no_tui and not self.args.quiet:
            from nettest.tui.app import NettestApp
            tui = NettestApp(
                bus=self.bus,
                cfg=self.cfg,
                hostname=self.hostname,
                events=self.events,
                scheduler=self.scheduler,
                ascii=self.args.ascii or self.cfg.ui.tui.ascii,
                no_color=self.args.no_color or self.cfg.ui.tui.no_color,
                theme=self.cfg.ui.tui.theme,
            )
            tui_task = asyncio.create_task(tui.run_async(), name="tui")
            tasks.append(tui_task)

        if self.args.duration_s:
            tasks.append(
                asyncio.create_task(
                    asyncio.sleep(self.args.duration_s), name="duration",
                )
            )

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.scheduler.stop()
            self.sqlite_sink.stop()
            self.jsonl_sink.stop()
            self.detector.stop()
            self.maintenance.stop()
            if web_server is not None:
                web_server.should_exit = True
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            event_db_conn.close()


def build_runtime(argv: list[str], data_dir: Path | None = None) -> Runtime:
    args = parse_args(argv)
    cfg_path = Path(args.config) if args.config else None
    cfg = load_config(
        config_path=cfg_path,
        search_dirs=[Path.cwd(), Path.home() / ".config" / "nettest"],
    )

    hostname = current_hostname()
    base = (data_dir or Path(cfg.storage.data_dir)) / hostname
    base.mkdir(parents=True, exist_ok=True)
    db_path = base / cfg.storage.sqlite.file

    msg = warn_if_public_bind(args.bind or cfg.ui.web.bind, list_interface_ips())
    if msg:
        print(msg, file=sys.stderr)

    bus = ResultBus()
    events = EventBroadcast()
    sqlite_sink = SqliteSink(bus=bus, db_path=db_path)
    jsonl_sink = JsonlSink(bus=bus, data_dir=base)

    detector = PatternDetector(bus=bus, cfg=cfg.patterns)  # on_event wired in Runtime.run()
    maintenance = StorageMaintenance(
        db_path=db_path,
        retain_raw_days=cfg.storage.retention.raw_results_days,
        retain_1m_days=cfg.storage.retention.rollups_1m_days,
        retain_1h_days=cfg.storage.retention.rollups_1h_days,
    )
    scheduler = Scheduler(bus=bus, hostname=hostname)
    probes = build_probes(cfg, hostname=hostname, filter_names=args.probes)
    rt_targets = resolve_targets(cfg)
    for name, probe in probes.items():
        targets: list[Target] = getattr(rt_targets, name, [])
        if targets:
            scheduler.add(probe, targets)

    return Runtime(
        args=args,
        cfg=cfg,
        bus=bus,
        scheduler=scheduler,
        sqlite_sink=sqlite_sink,
        jsonl_sink=jsonl_sink,
        detector=detector,
        maintenance=maintenance,
        db_path=db_path,
        hostname=hostname,
        events=events,
    )


async def run_snapshot(
    argv: list[str],
    data_dir: Path | None = None,
    duration_s: int = 30,
) -> None:
    args_with_duration = list(argv) + ["--no-tui", "--no-web", "--duration", f"{duration_s}s"]
    rt = build_runtime(args_with_duration, data_dir=data_dir)
    await rt.run()
    # summarize
    conn = sqlite3.connect(rt.db_path)
    try:
        rows = conn.execute(
            "SELECT probe, target, COUNT(*), SUM(ok), AVG(duration_ms) "
            "FROM results GROUP BY probe, target ORDER BY probe, target"
        ).fetchall()
    finally:
        conn.close()
    print("\nnettest snapshot summary")
    print("=" * 60)
    print(f"{'probe':14} {'target':30} {'count':>6} {'loss%':>6} {'avg_ms':>8}")
    for probe, target, count, ok_count, avg_ms in rows:
        loss = (1 - (ok_count or 0) / count) * 100 if count else 0
        print(
            f"{probe:14} {target[:30]:30} {count:>6} {loss:>6.1f} {avg_ms or 0:>8.1f}"
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = parse_args(sys.argv[1:])
    if args.snapshot:
        asyncio.run(run_snapshot(sys.argv[1:]))
        return
    if args.replay_db:
        from nettest.cli.replay import build_replay_app
        build_replay_app(Path(args.replay_db)).run()
        return
    rt = build_runtime(sys.argv[1:])
    try:
        asyncio.run(rt.run())
    except KeyboardInterrupt:
        log.info("interrupted")
