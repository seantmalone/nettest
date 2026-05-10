"""Tests for nettest.cli.args."""
from __future__ import annotations

from nettest.cli.args import parse_args


def test_parse_default() -> None:
    args = parse_args([])
    assert args.no_tui is False
    assert args.no_web is False
    assert args.duration_s is None


def test_parse_no_tui_no_web() -> None:
    args = parse_args(["--no-tui", "--no-web"])
    assert args.no_tui is True
    assert args.no_web is True


def test_parse_duration_human_units() -> None:
    assert parse_args(["--duration", "30s"]).duration_s == 30
    assert parse_args(["--duration", "5m"]).duration_s == 300
    assert parse_args(["--duration", "2h"]).duration_s == 7200


def test_parse_probes_filter() -> None:
    args = parse_args(["--probes", "ping,dns_cached"])
    assert args.probes == ["ping", "dns_cached"]


def test_parse_replay_implies_no_probing() -> None:
    args = parse_args(["--replay", "/tmp/x.db"])
    assert args.replay_db == "/tmp/x.db"


def test_parse_snapshot_mode() -> None:
    args = parse_args(["--snapshot"])
    assert args.snapshot is True


def test_parse_bind_localhost() -> None:
    args = parse_args(["--bind", "127.0.0.1"])
    assert args.bind == "127.0.0.1"
