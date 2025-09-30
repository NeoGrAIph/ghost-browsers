import pytest

from camofleet_vnc_gateway.config import GatewaySettings


def test_validate_port_accepts_within_range() -> None:
    settings = GatewaySettings(min_port=6000, max_port=6005)
    assert settings.validate_port("6001") == 6001


def test_validate_port_rejects_out_of_range() -> None:
    settings = GatewaySettings(min_port=6000, max_port=6005)
    with pytest.raises(ValueError):
        settings.validate_port("7000")


def test_validate_port_requires_integer() -> None:
    settings = GatewaySettings()
    with pytest.raises(ValueError):
        settings.validate_port("not-a-number")
