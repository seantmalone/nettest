"""Tests for nettest.cli.binding."""
from __future__ import annotations

from nettest.cli.binding import is_rfc1918, warn_if_public_bind


def test_rfc1918_classification() -> None:
    assert is_rfc1918("10.0.0.1") is True
    assert is_rfc1918("172.16.5.1") is True
    assert is_rfc1918("172.31.255.255") is True
    assert is_rfc1918("172.32.0.1") is False
    assert is_rfc1918("192.168.1.1") is True
    assert is_rfc1918("127.0.0.1") is True
    assert is_rfc1918("8.8.8.8") is False


def test_warn_if_public_bind_returns_message_for_public() -> None:
    msg = warn_if_public_bind("0.0.0.0", interfaces=["8.8.8.8"])
    assert msg is not None
    assert "8.8.8.8" in msg


def test_warn_if_public_bind_returns_none_for_private() -> None:
    msg = warn_if_public_bind("0.0.0.0", interfaces=["192.168.1.5"])
    assert msg is None


def test_warn_if_public_bind_returns_none_for_localhost_bind() -> None:
    msg = warn_if_public_bind("127.0.0.1", interfaces=["8.8.8.8"])
    assert msg is None
