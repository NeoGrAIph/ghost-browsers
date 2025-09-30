"""Camofleet control-plane application."""

"""Expose the FastAPI application factory for external imports."""

from .main import create_app

__all__ = ["create_app"]
