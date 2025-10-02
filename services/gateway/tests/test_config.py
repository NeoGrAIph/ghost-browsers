"""Tests for gateway configuration helpers."""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.config import GatewaySettings  # noqa: E402


def test_from_env_parses_trusted_cidrs() -> None:
    """`GatewaySettings.from_env` parses trusted CIDR blocks from the environment."""

    settings = GatewaySettings.from_env(
        {
            "GATEWAY_TRUSTED_CIDRS": "10.0.0.0/8, fd00::/64",
            "GATEWAY_TRUSTED_HEADER": " X-Real-IP ",
        }
    )

    assert settings.trusted_cidrs == [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("fd00::/64"),
    ]
    assert settings.trusted_header == "X-Real-IP"


def test_from_env_rejects_empty_cidr_entries() -> None:
    """Empty entries inside `GATEWAY_TRUSTED_CIDRS` raise a `ValueError`."""

    with pytest.raises(ValueError):
        GatewaySettings.from_env({"GATEWAY_TRUSTED_CIDRS": "10.0.0.0/8, ,192.0.2.0/24"})


def test_from_env_rejects_invalid_cidr() -> None:
    """Invalid CIDR notations cause a `ValueError` with a helpful message."""

    with pytest.raises(ValueError) as excinfo:
        GatewaySettings.from_env({"GATEWAY_TRUSTED_CIDRS": "not-a-network"})

    assert "GATEWAY_TRUSTED_CIDRS" in str(excinfo.value)
