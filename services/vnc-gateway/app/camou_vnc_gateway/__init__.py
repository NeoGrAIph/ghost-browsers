"""Application factory for the VNC gateway service.

This module exposes the :func:`create_app` helper used by tests and runtime
entrypoints to build a configured FastAPI application instance.
"""

from .main import create_app

__all__ = ["create_app"]
