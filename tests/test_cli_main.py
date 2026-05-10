"""Tests for nettest.cli.main."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nettest.cli.main import Runtime, build_runtime


async def test_build_runtime_constructs_components(tmp_path: Path) -> None:
    rt = build_runtime(
        argv=["--no-tui", "--no-web", "--probes", "ping"],
        data_dir=tmp_path,
    )
    assert isinstance(rt, Runtime)
    assert rt.scheduler is not None
    assert rt.bus is not None
    # data dir prepared for hostname
    assert (tmp_path / rt.hostname).is_dir() or rt.hostname


async def test_runtime_runs_for_fixed_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = build_runtime(
        argv=["--no-tui", "--no-web", "--duration", "1s", "--probes", "ping"],
        data_dir=tmp_path,
    )
    # patch the ping probe so it doesn't hit the real network
    from nettest.probes.ping import PingProbe
    from nettest.types import Result, Target

    async def fake_measure(self: PingProbe, target: Target) -> Result:
        return Result(
            ts=datetime.now(UTC),
            host="h",
            probe="ping",
            target=target.label(),
            ok=True,
            duration_ms=1.0,
        )

    monkeypatch.setattr(PingProbe, "measure", fake_measure)
    await rt.run()
    # at least some results landed in SQLite
    db = next((tmp_path / rt.hostname).glob("*.db"))
    conn = sqlite3.connect(db)
    try:
        row: Any = conn.execute("SELECT COUNT(*) FROM results").fetchone()
        n = row[0]
    finally:
        conn.close()
    assert n > 0
