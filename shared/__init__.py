"""Shared utilities used by multiple Camofleet services."""

from .version import __version__
from .websocket_bridge import bridge_websocket

__all__ = ["bridge_websocket", "__version__"]
