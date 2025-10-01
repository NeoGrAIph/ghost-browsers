"""Pytest configuration for the VNC gateway tests."""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_sessionstart(session) -> None:  # type: ignore[override]
    """Ensure the service package is importable for tests.

    Parameters
    ----------
    session:
        Pytest session object; unused but required by the hook signature.
    """

    root = Path(__file__).resolve().parents[1] / "app"
    sys.path.insert(0, str(root))
