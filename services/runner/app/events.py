"""Session event transport abstraction for the runner service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import anyio
from core.models import SessionEvent


class SessionEventPublisher(Protocol):
    """Protocol implemented by session event transports."""

    async def publish(self, event: SessionEvent) -> None:
        """Persist or forward a session lifecycle event."""


class InMemorySessionEventPublisher:
    """Store session events in memory for inspection during tests.

    The publisher acts as the default transport for local development and unit
    tests. Events are appended to an internal list protected by an
    :class:`anyio.Lock`, ensuring deterministic order even under concurrent
    access. Consumers can call :meth:`drain` to atomically snapshot the stored
    events.
    """

    def __init__(self) -> None:
        self._events: list[SessionEvent] = []
        self._lock = anyio.Lock()

    async def publish(self, event: SessionEvent) -> None:
        """Append ``event`` to the in-memory buffer."""

        async with self._lock:
            self._events.append(event)

    async def drain(self) -> list[SessionEvent]:
        """Return and clear the buffered events in FIFO order."""

        async with self._lock:
            drained = list(self._events)
            self._events.clear()
            return drained


class CallbackSessionEventPublisher:
    """Proxy session events to an arbitrary asynchronous callback.

    The helper is used by higher layers (for example SSE broadcasters or HTTP
    webhooks) to bridge the runner-facing event interface with existing
    infrastructure. The callback is awaited for each event, propagating
    exceptions back to the caller so that failures surface in tests.
    """

    def __init__(self, callback: Callable[[SessionEvent], Awaitable[None]]) -> None:
        self._callback = callback

    async def publish(self, event: SessionEvent) -> None:
        """Forward ``event`` to the configured callback."""

        await self._callback(event)


__all__ = [
    "CallbackSessionEventPublisher",
    "InMemorySessionEventPublisher",
    "SessionEventPublisher",
]
