"""Transport helpers for publishing workstation lifecycle events.

The runner emits :class:`core.WorkstationEvent` objects whenever warm pool
workstations change state.  This module mirrors the session event transport
implementations so tests can observe emitted events and production
installations can forward them to the gateway over HTTP.

Example:
    >>> publisher = InMemoryWorkstationEventPublisher()
    >>> async def main() -> None:
    ...     event = WorkstationEvent(...)
    ...     await publisher.publish(event)
    ...     drained = await publisher.drain()
    ...     assert drained[0] is event
    >>> # anyio.run(main)  # doctest: +SKIP
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import anyio
import httpx
from core import WorkstationEvent

__all__ = [
    "WorkstationEventPublisher",
    "InMemoryWorkstationEventPublisher",
    "CallbackWorkstationEventPublisher",
    "HttpWorkstationEventPublisher",
]


class WorkstationEventPublisher(Protocol):
    """Protocol implemented by workstation event transports."""

    async def publish(self, event: WorkstationEvent) -> None:
        """Persist or forward a workstation lifecycle event."""


class InMemoryWorkstationEventPublisher:
    """Store workstation events in memory for assertions during tests.

    The publisher mirrors :class:`InMemorySessionEventPublisher` and appends
    events to an internal FIFO list guarded by an :class:`anyio.Lock` to
    preserve ordering when invoked concurrently.
    """

    def __init__(self) -> None:
        self._events: list[WorkstationEvent] = []
        self._lock = anyio.Lock()

    async def publish(self, event: WorkstationEvent) -> None:
        """Append ``event`` to the in-memory buffer."""

        async with self._lock:
            self._events.append(event)

    async def drain(self) -> list[WorkstationEvent]:
        """Return and clear the buffered events in FIFO order."""

        async with self._lock:
            drained = list(self._events)
            self._events.clear()
            return drained


class CallbackWorkstationEventPublisher:
    """Proxy workstation events to an arbitrary asynchronous callback."""

    def __init__(self, callback: Callable[[WorkstationEvent], Awaitable[None]]) -> None:
        self._callback = callback

    async def publish(self, event: WorkstationEvent) -> None:
        """Forward ``event`` to the configured callback."""

        await self._callback(event)


class HttpWorkstationEventPublisher:
    """Publish workstation events to the gateway over HTTP.

    Args:
        endpoint: Absolute URL of the gateway endpoint accepting
            :class:`WorkstationEvent` payloads.
        client: Optional :class:`httpx.AsyncClient` to reuse across requests.
        timeout: Request timeout applied when instantiating ad-hoc clients.
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

    async def publish(self, event: WorkstationEvent) -> None:
        """Serialise ``event`` and POST it to the configured endpoint."""

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
