"""Pytest configuration for the VNC gateway tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

ROOT = Path(__file__).resolve().parents[1] / "app"


def _ensure_app_on_path() -> None:
    """Insert the application package directory into ``sys.path``."""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


_ensure_app_on_path()

from camou_vnc_gateway.dependencies import get_connection_registry  # noqa: E402
from camou_vnc_gateway.metrics import (  # noqa: E402
    PrometheusMetricsBackend,
    configure_metrics_backend,
)


def pytest_sessionstart(session) -> None:  # type: ignore[override]
    """Ensure the service package is importable for tests.

    Parameters
    ----------
    session:
        Pytest session object; unused but required by the hook signature.
    """

    _ensure_app_on_path()


@pytest.fixture(autouse=True)
def _reset_metrics_backend() -> None:
    """Reset the process-wide metrics backend between tests."""

    configure_metrics_backend(PrometheusMetricsBackend(CollectorRegistry()))
    if hasattr(get_connection_registry, "_registry"):
        delattr(get_connection_registry, "_registry")
    yield
    configure_metrics_backend(PrometheusMetricsBackend(CollectorRegistry()))
    if hasattr(get_connection_registry, "_registry"):
        delattr(get_connection_registry, "_registry")
