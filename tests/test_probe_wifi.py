import asyncio

from nettest.probes.base import ProbeContext
from nettest.probes.wifi import (
    WifiProbe,
    parse_airport_output,
    parse_iw_output,
    parse_netsh_output,
)
from nettest.types import Target


def test_parse_airport_mac():
    out = """\
     agrCtlRSSI: -52
     agrExtRSSI: 0
     agrCtlNoise: -90
     agrExtNoise: 0
       state: running
       op mode: station
        SSID: Home-5G
        BSSID: aa:bb:cc:dd:ee:ff
       channel: 36,80
   lastTxRate: 866
"""
    info = parse_airport_output(out)
    assert info["ssid"] == "Home-5G"
    assert info["rssi_dbm"] == -52
    assert info["noise_dbm"] == -90
    assert info["link_rate_mbps"] == 866
    assert info["channel"] == "36,80"
    assert info["bssid"] == "aa:bb:cc:dd:ee:ff"


def test_parse_netsh_windows():
    out = """\
There is 1 interface on the system:

    Name                   : Wi-Fi
    SSID                   : Home-5G
    BSSID                  : aa:bb:cc:dd:ee:ff
    Signal                 : 88%
    Channel                : 36
    Receive rate (Mbps)    : 866
    Transmit rate (Mbps)   : 866
"""
    info = parse_netsh_output(out)
    assert info["ssid"] == "Home-5G"
    assert info["bssid"] == "aa:bb:cc:dd:ee:ff"
    assert info["link_rate_mbps"] == 866
    assert info["rssi_dbm"] is not None


def test_parse_iw_linux():
    out = """\
Connected to aa:bb:cc:dd:ee:ff (on wlan0)
        SSID: Home-5G
        freq: 5180
        signal: -52 dBm
        tx bitrate: 866.7 MBit/s
"""
    info = parse_iw_output(out)
    assert info["ssid"] == "Home-5G"
    assert info["rssi_dbm"] == -52
    assert info["bssid"] == "aa:bb:cc:dd:ee:ff"


def test_parse_system_profiler_mac():
    out = """\
            Current Network Information:
              Home-5G:
                PHY Mode: 802.11ax
                BSSID: aa:bb:cc:dd:ee:ff
                Channel: 36 (5GHz, 80MHz)
                Signal / Noise: -52 dBm / -90 dBm
                Transmit Rate: 866
"""
    from nettest.probes.wifi import parse_system_profiler_output
    info = parse_system_profiler_output(out)
    assert info["ssid"] == "Home-5G"
    assert info["bssid"] == "aa:bb:cc:dd:ee:ff"
    assert info["rssi_dbm"] == -52
    assert info["noise_dbm"] == -90
    assert info["link_rate_mbps"] == 866


def test_parse_iw_dev_lists_interfaces():
    out = """\
phy#0
\tInterface wlp3s0
\t\tifindex 3
\t\twdev 0x1
\t\taddr aa:bb:cc:dd:ee:ff
\t\ttype managed
"""
    from nettest.probes.wifi import _iw_dev_interfaces
    assert _iw_dev_interfaces(out) == ["wlp3s0"]


async def test_wifi_probe_returns_failure_when_disabled():
    ctx = ProbeContext(hostname="h", interval_ms=1000, timeout_ms=1000)
    probe = WifiProbe(ctx, enabled=False)
    res = await probe.run(Target(kind="host", host="local"), cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "disabled"


async def test_wifi_probe_reports_wifi_off_on_mac():
    """When `system_profiler` reports Wi-Fi powered off, return a clear error."""
    from unittest.mock import patch

    sp_off_out = """\
Wi-Fi:

      Software Versions:
          CoreWLAN: 16.0
      Interfaces:
        en0:
          Card Type: Wi-Fi
          MAC Address: 9a:16:69:8b:63:99
          Status: Off
"""

    async def fake_run(cmd):
        if cmd[0].endswith("airport"):
            return (1, "")  # airport tool failed/missing
        if cmd[0] == "system_profiler":
            return (0, sp_off_out)
        return (-1, "")

    ctx = ProbeContext(hostname="h", interval_ms=1000, timeout_ms=2000)
    probe = WifiProbe(ctx, enabled=True)
    with (
        patch("nettest.probes.wifi.platform.system", return_value="Darwin"),
        patch("nettest.probes.wifi._run_cmd", side_effect=fake_run),
    ):
        res = await probe.run(Target(kind="host", host="local"), cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "wifi off"


async def test_wifi_probe_reports_not_connected_on_mac():
    """system_profiler runs but there's no 'Current Network Information' section."""
    from unittest.mock import patch

    sp_out = """\
Wi-Fi:
      Interfaces:
        en0:
          Card Type: Wi-Fi
          Status: On
"""

    async def fake_run(cmd):
        if cmd[0].endswith("airport"):
            return (1, "")
        if cmd[0] == "system_profiler":
            return (0, sp_out)
        return (-1, "")

    ctx = ProbeContext(hostname="h", interval_ms=1000, timeout_ms=2000)
    probe = WifiProbe(ctx, enabled=True)
    with (
        patch("nettest.probes.wifi.platform.system", return_value="Darwin"),
        patch("nettest.probes.wifi._run_cmd", side_effect=fake_run),
    ):
        res = await probe.run(Target(kind="host", host="local"), cancel=asyncio.Event())
    assert res.ok is False
    assert res.error == "not connected to wifi"
