"""Pytest configuration for core package tests."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(_CORE_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_PACKAGE_ROOT))
