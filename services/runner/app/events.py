"""Session event transport abstraction for the runner service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
"""Event publisher abstractions for session and workstation lifecycles."""

from typing import Protocol

import anyio
import httpx
from core.models import SessionEvent, WorkstationEvent


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


class WorkstationEventPublisher(Protocol):
    """Protocol describing transports for workstation lifecycle events."""

    async def publish(self, event: WorkstationEvent) -> None:
        """Forward ``event`` to downstream consumers."""


class InMemoryWorkstationEventPublisher:
    """Collect workstation events in FIFO order for deterministic tests."""

    def __init__(self) -> None:
        self._events: list[WorkstationEvent] = []
        self._lock = anyio.Lock()

    async def publish(self, event: WorkstationEvent) -> None:
        """Append ``event`` to the buffer in a concurrency-safe manner."""

        async with self._lock:
            self._events.append(event)

    async def drain(self) -> list[WorkstationEvent]:
        """Return and clear buffered events atomically."""

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


class HttpSessionEventPublisher:
    """Publish session events to the gateway over HTTP.

    Args:
        endpoint: Absolute URL of the gateway endpoint that accepts
            ``SessionEvent`` payloads.
        client: Optional :class:`httpx.AsyncClient` instance that will be used
            for requests. When omitted a short-lived client is created for each
            call.
        timeout: Request timeout applied when instantiating internal clients.

    Example:
        >>> publisher = HttpSessionEventPublisher("https://gateway/events")
        >>> await publisher.publish(event)  # doctest: +SKIP
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._endpoint = endpoint
        self._client = client
        self._timeout = timeout

    async def publish(self, event: SessionEvent) -> None:
        """Serialise ``event`` and POST it to the configured gateway endpoint.

        Args:
            event: Immutable session event to send upstream.

        Returns:
            None. The coroutine completes once the gateway acknowledges the
            request with a successful HTTP status code.

        Raises:
            httpx.HTTPStatusError: If the gateway responds with a non-success
                status code.
            httpx.RequestError: If the HTTP request fails before receiving a
                response.
        """

        payload = event.model_dump(mode="json", by_alias=True)
        if self._client is not None:
            response = await self._client.post(
                self._endpoint,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            return

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()


__all__ = [
    "CallbackSessionEventPublisher",
    "HttpSessionEventPublisher",
    "InMemorySessionEventPublisher",
    "InMemoryWorkstationEventPublisher",
    "SessionEventPublisher",
    "WorkstationEventPublisher",
]
