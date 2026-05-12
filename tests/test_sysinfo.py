"""Tests for nettest.sysinfo."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from nettest import sysinfo
from nettest.sysinfo import SysInfo, SysInfoCache


async def test_gather_returns_sysinfo_dataclass():
    with (
        patch.object(sysinfo, "default_route", AsyncMock(return_value=("en0", "10.0.0.1"))),
        patch.object(sysinfo, "local_ip_for_iface", AsyncMock(return_value="10.0.0.42")),
        patch.object(sysinfo, "public_ip", AsyncMock(return_value="203.0.113.7")),
        patch.object(
            sysinfo, "wifi_info",
            AsyncMock(return_value=("MyWiFi", "aa:bb:cc:dd:ee:ff", -55)),
        ),
    ):
        info = await sysinfo.gather()
    assert info.default_iface == "en0"
    assert info.default_gateway == "10.0.0.1"
    assert info.local_ip == "10.0.0.42"
    assert info.public_ip == "203.0.113.7"
    assert info.wifi_ssid == "MyWiFi"
    assert info.wifi_bssid == "aa:bb:cc:dd:ee:ff"
    assert info.wifi_signal_dbm == -55
    assert info.wifi_state == "connected"
    assert info.public_ip_state == "available"


async def test_gather_marks_wifi_off_when_no_association_and_radio_off():
    with (
        patch.object(sysinfo, "default_route", AsyncMock(return_value=("en0", "10.0.0.1"))),
        patch.object(sysinfo, "local_ip_for_iface", AsyncMock(return_value="10.0.0.42")),
        patch.object(sysinfo, "public_ip", AsyncMock(return_value=None)),
        patch.object(sysinfo, "wifi_info", AsyncMock(return_value=(None, None, None))),
        patch.object(sysinfo, "is_wifi_likely_available", lambda: False),
    ):
        info = await sysinfo.gather()
    assert info.wifi_state == "off"
    assert info.public_ip_state == "unavailable"


async def test_gather_marks_wifi_not_connected_when_radio_on_but_no_assoc():
    with (
        patch.object(sysinfo, "default_route", AsyncMock(return_value=("en0", "10.0.0.1"))),
        patch.object(sysinfo, "local_ip_for_iface", AsyncMock(return_value="10.0.0.42")),
        patch.object(sysinfo, "public_ip", AsyncMock(return_value=None)),
        patch.object(sysinfo, "wifi_info", AsyncMock(return_value=(None, None, None))),
        patch.object(sysinfo, "is_wifi_likely_available", lambda: True),
    ):
        info = await sysinfo.gather()
    assert info.wifi_state == "not_connected"


async def test_sysinfo_to_dict_contains_expected_keys():
    info = SysInfo(wifi_ssid="x", default_iface="en0")
    d = info.to_dict()
    assert set(d.keys()) == {
        "wifi_ssid", "wifi_bssid", "wifi_signal_dbm", "wifi_state",
        "default_iface", "default_gateway",
        "local_ip", "public_ip", "public_ip_state",
    }


def test_wifi_label_uses_ssid_when_present():
    info = SysInfo(wifi_ssid="MyNet", wifi_bssid="aa:bb:cc:dd:ee:ff")
    assert info.wifi_label() == "MyNet"


def test_wifi_label_falls_back_to_bssid_when_redacted():
    info = SysInfo(wifi_ssid="<redacted>", wifi_bssid="aa:bb:cc:dd:ee:ff")
    assert info.wifi_label() == "(hidden) aa:bb:cc:dd:ee:ff"


def test_wifi_label_returns_none_when_no_association():
    assert SysInfo().wifi_label() is None


def test_wifi_label_indicates_macos_redaction_when_ssid_only_is_redacted():
    info = SysInfo(wifi_ssid="<redacted>")
    assert info.wifi_label() == "(SSID hidden by macOS)"


def test_wifi_label_indicates_redaction_when_only_rssi_known():
    info = SysInfo(wifi_signal_dbm=-67)
    assert info.wifi_label() == "(SSID hidden by macOS)"


async def test_sysinfo_cache_run_refreshes_snapshot():
    import asyncio
    cache = SysInfoCache(refresh_interval_s=0.01)
    fake = SysInfo(local_ip="10.0.0.42")
    with patch.object(sysinfo, "gather", AsyncMock(return_value=fake)):
        task = asyncio.create_task(cache.run())
        for _ in range(50):
            if cache.snapshot().local_ip == "10.0.0.42":
                break
            await asyncio.sleep(0.005)
        task.cancel()
        await task
    assert cache.snapshot().local_ip == "10.0.0.42"


async def test_sysinfo_cache_survives_gather_exception():
    import asyncio
    cache = SysInfoCache(refresh_interval_s=0.01)
    with patch.object(sysinfo, "gather", AsyncMock(side_effect=RuntimeError("boom"))):
        task = asyncio.create_task(cache.run())
        await asyncio.sleep(0.05)
        task.cancel()
        await task
    # Snapshot remains the default-constructed sysinfo despite failures.
    assert cache.snapshot().local_ip is None
