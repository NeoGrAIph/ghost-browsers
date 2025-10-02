"""Synchronous Camoufox API shim that proxies to the official SDK."""

from __future__ import annotations

from types import ModuleType

from . import _load_sdk_module


_SYNC_API: ModuleType = _load_sdk_module("sync_api")
"""Reference to the upstream synchronous Camoufox module."""

Camoufox = _SYNC_API.Camoufox
NewBrowser = getattr(_SYNC_API, "NewBrowser")

__all__ = ["Camoufox", "NewBrowser"]
