"""Shared version utilities for Camofleet services."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _ROOT / "VERSION"

__version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()


__all__ = ["__version__"]
