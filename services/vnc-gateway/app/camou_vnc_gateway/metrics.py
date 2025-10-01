"""Light-weight connection tracking utilities.

The first iteration of the service does not integrate with a full metrics
pipeline yet.  Nevertheless the service keeps track of active connections per
session in order to facilitate debugging and future observability work.  The
:class:`ConnectionRegistry` exposes a small asynchronous context manager which
increments counters for the duration of a proxy operation and produces log
records describing the current utilisation.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from contextlib import asynccontextmanager
from typing import AsyncIterator

LOG = logging.getLogger(__name__)


class ConnectionRegistry:
    """Track active HTTP and WebSocket connections per session.

    The registry is intentionally simple: it stores counters in-memory and
    relies on cooperative scheduling through :mod:`asyncio`.  This suffices for
    unit tests and local development where the process lifetime is short-lived
    and the set of tracked sessions is limited.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = Counter()

    @asynccontextmanager
    async def track(self, *, session_id: str, channel: str) -> AsyncIterator[None]:
        """Context manager used to track a proxied connection lifecycle.

        Parameters
        ----------
        session_id:
            Identifier of the session currently being proxied.
        channel:
            Human readable channel label (e.g. ``"http"`` or ``"ws"``).
        """

        key = (session_id, channel)
        async with self._lock:
            self._active[key] += 1
            LOG.info(
                "connection.started",
                extra={"session_id": session_id, "channel": channel, "active": self._active[key]},
            )
        try:
            yield
        finally:
            async with self._lock:
                self._active[key] -= 1
                LOG.info(
                    "connection.finished",
                    extra={
                        "session_id": session_id,
                        "channel": channel,
                        "active": self._active[key],
                    },
                )

    async def snapshot(self) -> dict[tuple[str, str], int]:
        """Return a shallow copy of the current counter state."""

        async with self._lock:
            return dict(self._active)


__all__ = ["ConnectionRegistry"]
