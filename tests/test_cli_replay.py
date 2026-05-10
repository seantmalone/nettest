"""Tests for nettest.cli.replay."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from nettest.cli.replay import build_replay_app
from nettest.storage.schema import init_schema


def test_replay_app_uses_existing_db(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    init_schema(conn)
    conn.close()
    app = build_replay_app(db_path=db)
    assert app is not None
