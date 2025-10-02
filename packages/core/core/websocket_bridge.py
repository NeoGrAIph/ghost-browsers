"""Asynchronous utilities for propagating session and workstation events.

Ghost Browsers standardises on in-memory fan-out bridges backed by
``asyncio`` primitives rather than external brokers. The same pattern is
reused for session and workstation events so downstream services can
subscribe using a consistent API regardless of event type.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import AsyncGenerator

from .models import SessionEvent, WorkstationEvent


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
        """Initialise the bridge with no subscribers."""

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
            try:
                while True:
                    yield await queue.get()
            finally:
                async with self._lock:
                    self._subscribers.discard(queue)

        return iterator()


class AbstractWorkstationEventBridge(ABC):
    """Common interface for broadcasting workstation events to subscribers."""

    @abstractmethod
    async def publish(self, event: WorkstationEvent) -> None:
        """Publish a workstation event to all subscribers."""

    @abstractmethod
    async def subscribe(
        self, *, replay_latest: bool = False
    ) -> AsyncIterator[WorkstationEvent]:
        """Return an async iterator yielding workstation events."""


class InMemoryWorkstationEventBridge(AbstractWorkstationEventBridge):
    """In-memory bridge that fans out workstation events to subscribers."""

    def __init__(self) -> None:
        """Initialise the bridge with no subscribers."""

        self._subscribers: set[asyncio.Queue[WorkstationEvent]] = set()
        self._lock = asyncio.Lock()
        self._latest_event: WorkstationEvent | None = None

    async def publish(self, event: WorkstationEvent) -> None:
        """Broadcast ``event`` to all currently subscribed consumers."""

        async with self._lock:
            queues = list(self._subscribers)
            self._latest_event = event
        for queue in queues:
            await queue.put(event)

    async def subscribe(
        self, *, replay_latest: bool = False
    ) -> AsyncIterator[WorkstationEvent]:
        """Register a subscriber and return an iterator of workstation events."""

        queue: asyncio.Queue[WorkstationEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            latest = self._latest_event

        if replay_latest and latest is not None:
            await queue.put(latest)

        async def iterator() -> AsyncGenerator[WorkstationEvent, None]:
            try:
                while True:
                    yield await queue.get()
            finally:
                async with self._lock:
                    self._subscribers.discard(queue)

        return iterator()
