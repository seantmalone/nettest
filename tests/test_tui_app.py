from datetime import UTC, datetime

from textual.widgets import Static

from nettest.bus import ResultBus
from nettest.config import Config
from nettest.events import Event
from nettest.tui.app import NettestApp
from nettest.tui.event_broadcast import EventBroadcast
from nettest.types import Result


async def test_app_starts_and_renders_header():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="test-host", events=eb)
    async with app.run_test() as pilot:
        await pilot.pause()
        banner = app.query_one("#banner", Static)
        assert "test-host" in str(banner.render())


async def test_app_records_published_result():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb)
    async with app.run_test() as pilot:
        await bus.publish(Result(
            ts=datetime.now(UTC), host="h", probe="ping",
            target="1.1.1.1", ok=True, duration_ms=12.5,
        ))
        await pilot.pause()
        agg = app.aggregators.get(("ping", "1.1.1.1"))
        assert agg is not None
        assert agg.snapshot().last_ms == 12.5


async def test_app_receives_events_via_broadcast():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb)
    async with app.run_test() as pilot:
        eb.publish(Event(
            ts_start=datetime.now(UTC), ts_end=datetime.now(UTC),
            kind="micro_outage", severity="warn", summary="boom",
        ))
        await pilot.pause()
        assert any(e.kind == "micro_outage" for e in app._events)


async def test_q_keybinding_quits():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb)
    async with app.run_test() as pilot:
        await pilot.press("q")
        await pilot.pause()
        assert app._is_quitting is True


async def test_ascii_flag_uses_ascii_icons():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb, ascii=True)
    assert app._icons["ping"].startswith("[")
