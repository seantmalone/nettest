"""End-to-end smoke test: nettest probes a local HTTP server."""
from __future__ import annotations

import http.server
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.slow
async def test_full_stack_runs_for_2s_against_local_http(tmp_path: Path) -> None:
    """Spin up a local HTTP server, run nettest against it for 2s, verify rows."""
    handler = http.server.SimpleHTTPRequestHandler
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from nettest.cli.main import build_runtime
        from nettest.types import Target

        rt = build_runtime(
            argv=[
                "--no-tui", "--no-web", "--duration", "2s",
                "--probes", "tcp_connect",
            ],
            data_dir=tmp_path,
        )
        # add a TCP target manually — default config has no tcp targets, so
        # build_runtime didn't register a job; rebuild the probe and register.
        from nettest.probes.base import ProbeContext
        from nettest.probes.tcp_connect import TcpConnectProbe

        probe = TcpConnectProbe(
            ProbeContext(hostname=rt.hostname, interval_ms=200, timeout_ms=1000),
        )
        rt.scheduler.add(probe, [Target(kind="tcp", host="127.0.0.1", port=port)])
        await rt.run()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    db = next((tmp_path / rt.hostname).glob("*.db"))
    conn = sqlite3.connect(db)
    try:
        row: Any = conn.execute("SELECT COUNT(*) FROM results").fetchone()
        n = row[0]
    finally:
        conn.close()
    assert n > 0
