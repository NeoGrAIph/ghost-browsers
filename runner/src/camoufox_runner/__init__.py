"""Camoufox runner package."""

from __future__ import annotations

from typing import Any


def create_app(*args: Any, **kwargs: Any):  # pragma: no cover - thin wrapper
    """Import and invoke :func:`camoufox_runner.main.create_app` lazily."""

    from .main import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = ["create_app"]
