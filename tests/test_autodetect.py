from unittest.mock import patch

import pytest

from nettest import autodetect


@pytest.fixture
def mac_route_output():
    return """\
   route to: default
destination: default
       gateway: 192.168.1.1
       interface: en0
"""


def test_detect_gateway_mac(mac_route_output: str):
    with (
        patch("platform.system", return_value="Darwin"),
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = mac_route_output
        run.return_value.returncode = 0
        assert autodetect.default_gateway() == "192.168.1.1"


def test_detect_gateway_linux():
    out = "default via 10.0.0.1 dev eth0 proto dhcp metric 100\n"
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = out
        run.return_value.returncode = 0
        assert autodetect.default_gateway() == "10.0.0.1"


def test_detect_gateway_windows():
    out = """
Interface 0
  0.0.0.0/0  192.168.0.1  Manual    25
"""
    with (
        patch("platform.system", return_value="Windows"),
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = out
        run.return_value.returncode = 0
        assert autodetect.default_gateway() == "192.168.0.1"


def test_detect_gateway_none_when_no_route():
    with (
        patch("platform.system", return_value="Darwin"),
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = "no route to host"
        run.return_value.returncode = 1
        assert autodetect.default_gateway() is None


def test_detect_system_dns_resolvers_mac():
    sample = """
resolver #1
  nameserver[0] : 192.168.1.1
  nameserver[1] : 8.8.8.8
"""
    with (
        patch("platform.system", return_value="Darwin"),
        patch("subprocess.run") as run,
    ):
        run.return_value.stdout = sample
        run.return_value.returncode = 0
        assert autodetect.system_dns_resolvers() == ["192.168.1.1", "8.8.8.8"]
