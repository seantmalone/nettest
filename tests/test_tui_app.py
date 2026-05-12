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


async def test_q_keybinding_quits_and_cancels_consume_task():
    # Regression test for T4: quitting must cancel the consume task and
    # pause the scheduler, otherwise reactives may still tick after teardown.
    class _Sched:
        def __init__(self) -> None:
            self.paused = False
            self.resumed = False

        def pause(self) -> None:
            self.paused = True

        def resume(self) -> None:
            self.resumed = True

    sched = _Sched()
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb, scheduler=sched)
    async with app.run_test() as pilot:
        await pilot.pause()
        consume_task = app._consume_task
        await pilot.press("q")
        await pilot.pause()
        assert app._is_quitting is True
        assert sched.paused is True
        assert consume_task is None or consume_task.done()


async def test_ascii_flag_uses_ascii_icons():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb, ascii=True)
    assert app._icons["ping"].startswith("[")


async def test_severity_filter_cycles_through_settings():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Force a known starting point — the dotfile may persist state
        # across test runs on a developer machine.
        app._severity_filter = "all"
        app.action_cycle_severity_filter()
        assert app._severity_filter == "warn"
        app.action_cycle_severity_filter()
        assert app._severity_filter == "critical"
        app.action_cycle_severity_filter()
        assert app._severity_filter == "all"


async def test_pause_toggles_banner_and_freezes_refresh():
    cfg = Config()
    bus = ResultBus()
    eb = EventBroadcast()
    app = NettestApp(bus=bus, cfg=cfg, hostname="h", events=eb)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._paused is False
        await pilot.press("p")
        await pilot.pause()
        assert app._paused is True
        banner_text = str(app.query_one("#banner", Static).render())
        assert "PAUSED" in banner_text
        await pilot.press("p")
        await pilot.pause()
        assert app._paused is False
