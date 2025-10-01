"""In-memory session registry used by the gateway routers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from core import Session, SessionProxySettings


class SessionRegistry:
    """Concurrency-safe container that holds active sessions."""

    def __init__(self) -> None:
        """Initialise the registry with no sessions tracked."""

        self._sessions: dict[UUID, Session] = {}
        self._lock = asyncio.Lock()

    async def add(self, session: Session) -> Session:
        """Register a new session instance.

        Args:
            session: Session object reported by a runner.

        Returns:
            Session: The stored session instance (identical to ``session``).

        Raises:
            ValueError: If a session with the same identifier already exists.
        """

        async with self._lock:
            if session.id in self._sessions:
                raise ValueError("Session already exists")
            self._sessions[session.id] = session
            return session

    async def list(self) -> list[Session]:
        """Return all registered sessions in insertion order."""

        async with self._lock:
            return list(self._sessions.values())

    async def get(self, session_id: UUID) -> Session:
        """Retrieve a session by identifier."""

        async with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:  # pragma: no cover - trivial guard
                raise KeyError("Session not found") from exc

    async def delete(self, session_id: UUID) -> None:
        """Remove a session from the registry."""

        async with self._lock:
            try:
                del self._sessions[session_id]
            except KeyError as exc:  # pragma: no cover - trivial guard
                raise KeyError("Session not found") from exc

    async def update_proxy(self, session_id: UUID, proxy: SessionProxySettings) -> Session:
        """Attach or replace the proxy configuration for a session."""

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("Session not found")
            updated = session.model_copy(update={"proxy": proxy})
            self._sessions[session_id] = updated
            return updated

    async def touch(
        self,
        session_id: UUID,
        *,
        timestamp: datetime | None = None,
    ) -> Session:
        """Update the ``last_seen_at`` timestamp for a session."""

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError("Session not found")
            observed_at = timestamp or datetime.now(tz=UTC)
            updated = session.model_copy(update={"last_seen_at": observed_at})
            self._sessions[session_id] = updated
            return updated
