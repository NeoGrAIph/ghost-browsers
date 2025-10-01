"""Asynchronous utilities for propagating session events via WebSockets.

The real gateway will bridge events from runners to UI subscribers using
Redis streams or another broker. This module defines the abstract API
and provides an in-memory implementation that is suitable for unit tests
and local development.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import AsyncGenerator

from .models import SessionEvent


class AbstractSessionEventBridge(ABC):
    """Common interface for broadcasting session events to subscribers."""

    @abstractmethod
    async def publish(self, event: SessionEvent) -> None:
        """Publish an event to all subscribers.

        Args:
            event: Session event to forward to subscribers.

        Returns:
            None. Subclasses should fan out the payload to active consumers.
        """

    @abstractmethod
    async def subscribe(self, *, replay_latest: bool = False) -> AsyncIterator[SessionEvent]:
        """Return an async iterator yielding events as they arrive.

        Args:
            replay_latest: When ``True`` the latest published event is replayed to
                the subscriber before new events are streamed. This is useful for
                UI clients that reconnect and need an immediate snapshot.

        Returns:
            AsyncIterator[SessionEvent]: Stream that yields events in FIFO order.
        """


class InMemorySessionEventBridge(AbstractSessionEventBridge):
    """Simple bridge that fans out events to in-memory queues.

    The implementation is concurrency-safe and allows multiple
    subscribers. Each subscriber receives a dedicated queue, and the
    bridge ensures cleanup when a subscriber drops out by exiting the
    async iterator. The most recently published event is cached so a
    reconnecting subscriber can request an immediate replay via
    ``replay_latest``.

    Example:
        >>> bridge = InMemorySessionEventBridge()
        >>> async def consumer():
        ...     async for event in await bridge.subscribe():
        ...         print(event.session.id)
    """

    def __init__(self) -> None:
        """Initialise the bridge with no subscribers.

        Returns:
            None.
        """

        self._subscribers: set[asyncio.Queue[SessionEvent]] = set()
        self._lock = asyncio.Lock()
        self._latest_event: SessionEvent | None = None

    async def publish(self, event: SessionEvent) -> None:
        """Broadcast an event to all currently subscribed consumers.

        Args:
            event: Session event received from a runner.

        Returns:
            None. The event is enqueued for every active subscriber.
        """

        async with self._lock:
            queues = list(self._subscribers)
            self._latest_event = event
        for queue in queues:
            await queue.put(event)

    async def subscribe(self, *, replay_latest: bool = False) -> AsyncIterator[SessionEvent]:
        """Register a subscriber and return an async iterator of events.

        Args:
            replay_latest: When ``True`` the most recent event is enqueued
                immediately before live streaming begins.

        Returns:
            AsyncIterator[SessionEvent]: Stream that terminates when the
            consumer breaks from the loop or closes the generator.
        """

        queue: asyncio.Queue[SessionEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            latest = self._latest_event

        if replay_latest and latest is not None:
            await queue.put(latest)

        async def iterator() -> AsyncGenerator[SessionEvent, None]:
            """Yield events for a single subscriber until cancellation.

            Yields:
                SessionEvent: Events published by the bridge in FIFO order.

            Raises:
                asyncio.CancelledError: Propagated when the consumer cancels the iterator.
            """

            try:
                while True:
                    yield await queue.get()
            finally:
                async with self._lock:
                    self._subscribers.discard(queue)

        return iterator()
