"""Common pytest fixtures for the camoufox worker test suite."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Iterator

import pytest

_ENV_VARS_TO_RESET = [
    "WORKER_MODE",
    "GATEWAY_URL",
    "GATEWAY_TOKEN",
    "CAMOUFOX_HEADLESS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


if "camoufox" not in sys.modules:
    camoufox_module = types.ModuleType("camoufox")
    camoufox_sync_api_module = types.ModuleType("camoufox.sync_api")
    camoufox_errors_module = types.ModuleType("camoufox.errors")

    class _CamoufoxError(Exception):
        """Fallback Camoufox error stub for tests."""

    class _Camoufox:  # pragma: no cover - shim replaced in tests
        """Minimal Camoufox stub replaced with recording doubles in tests."""

        def __init__(self, *args, **kwargs) -> None:
            """Accept arbitrary parameters to match the real Camoufox signature."""

        def __enter__(self):
            """Return the stub instance when entering the context manager."""

            return self

        def __exit__(self, exc_type, exc, tb):
            """Propagate exceptions to the caller without suppression."""

            return False

    camoufox_errors_module.CamoufoxError = _CamoufoxError
    camoufox_sync_api_module.Camoufox = _Camoufox  # type: ignore[assignment]

    camoufox_module.sync_api = camoufox_sync_api_module  # type: ignore[attr-defined]
    camoufox_module.errors = camoufox_errors_module  # type: ignore[attr-defined]

    sys.modules["camoufox"] = camoufox_module
    sys.modules["camoufox.sync_api"] = camoufox_sync_api_module
    sys.modules["camoufox.errors"] = camoufox_errors_module


@pytest.fixture(autouse=True)
def reset_worker_environment() -> Iterator[None]:
    """Capture and restore worker-related environment variables around tests."""

    snapshot = {name: os.environ.get(name) for name in _ENV_VARS_TO_RESET}
    try:
        yield
    finally:
        for name, value in snapshot.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
