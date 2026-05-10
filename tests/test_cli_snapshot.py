"""Tests for nettest.cli.main.run_snapshot."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nettest.cli.main import run_snapshot


async def test_snapshot_prints_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from nettest.probes.ping import PingProbe
    from nettest.types import Result, Target

    async def fake_measure(self: PingProbe, target: Target) -> Result:
        return Result(
            ts=datetime.now(UTC),
            host="h",
            probe="ping",
            target=target.label(),
            ok=True,
            duration_ms=5.0,
        )

    monkeypatch.setattr(PingProbe, "measure", fake_measure)
    await run_snapshot(argv=["--probes", "ping"], data_dir=tmp_path, duration_s=1)
    out = capsys.readouterr().out
    assert "ping" in out
    assert "loss" in out.lower()
