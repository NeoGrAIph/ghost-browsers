"""Core package public API for Camou Core models and utilities.

This module re-exports the shared Pydantic models that define the
contract between Runner, Gateway, VNC Gateway, and UI services, along
with the abstract WebSocket bridge utilities used to relay session
events. Import from this module instead of the submodules to provide a
stable surface for downstream consumers.

Example:
    from core import Runner, Session, SessionEvent, InMemorySessionEventBridge

    runner = Runner(id="runner-1", base_url="http://runner-1:8080", total_slots=4)
    bridge = InMemorySessionEventBridge()
    # Use the bridge to publish and consume session lifecycle events.
    # New subscribers can request the latest snapshot using ``replay_latest=True``.
"""

from .models import (
    Runner,
    RunnerState,
    Session,
    SessionEvent,
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
    StartUrlWait,
)
from .websocket_bridge import (
    AbstractSessionEventBridge,
    InMemorySessionEventBridge,
)

__all__ = [
    "Runner",
    "RunnerState",
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionProxySettings",
    "SessionStatus",
    "StartUrlWait",
    "SessionVncDetails",
    "AbstractSessionEventBridge",
    "InMemorySessionEventBridge",
]
