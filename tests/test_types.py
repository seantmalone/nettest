from datetime import datetime, timezone

import pytest

from nettest.types import Result, Target


def test_result_minimal_construction():
    r = Result(
        ts=datetime(2026, 5, 10, 18, 42, 31, 241000, tzinfo=timezone.utc),
        host="sean-mbp",
        probe="ping",
        target="1.1.1.1",
        ok=True,
        duration_ms=14.2,
    )
    assert r.ok is True
    assert r.error is None
    assert r.metrics == {}
    assert r.tags == []


def test_result_to_json_dict_serializes_iso_utc():
    r = Result(
        ts=datetime(2026, 5, 10, 18, 42, 31, 241000, tzinfo=timezone.utc),
        host="sean-mbp",
        probe="http",
        target="https://google.com",
        ok=False,
        duration_ms=2400.0,
        error="timeout",
        metrics={"dns_ms": 3.1, "status": 0},
    )
    d = r.to_json_dict()
    assert d["ts"] == "2026-05-10T18:42:31.241000+00:00"
    assert d["ok"] is False
    assert d["error"] == "timeout"
    assert d["metrics"]["dns_ms"] == 3.1


def test_result_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="UTC"):
        Result(
            ts=datetime(2026, 5, 10, 18, 42, 31),  # no tz
            host="x",
            probe="ping",
            target="1.1.1.1",
            ok=True,
            duration_ms=1.0,
        )


def test_result_rejects_non_utc_timestamp():
    from datetime import timedelta as _td, timezone as _tz
    with pytest.raises(ValueError, match="UTC"):
        Result(
            ts=datetime(2026, 5, 10, 18, 42, 31, tzinfo=_tz(_td(hours=-5))),
            host="x", probe="ping", target="1.1.1.1",
            ok=True, duration_ms=1.0,
        )


def test_target_dns_kind():
    t = Target(kind="dns", host="google.com", resolver="1.1.1.1")
    assert t.label() == "dns:1.1.1.1/google.com"


def test_target_tcp_kind_requires_port():
    with pytest.raises(ValueError, match="port"):
        Target(kind="tcp", host="smtp.example.com")
