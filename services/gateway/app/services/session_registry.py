"""In-memory session registry used by the gateway routers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
            Session: The stored session instance with transient VNC token data
            removed.

        Raises:
            ValueError: If a session with the same identifier already exists.
        """

        async with self._lock:
            if session.id in self._sessions:
                raise ValueError("Session already exists")
            sanitized = self._sanitize_session(session)
            self._sessions[session.id] = sanitized
            return sanitized

    async def list(self) -> list[Session]:
        """Return all registered sessions in insertion order."""

        async with self._lock:
            return list(self._sessions.values())

    async def upsert(self, session: Session) -> Session:
        """Insert or replace a session entry and return the stored instance.

        Args:
            session: Session object whose identifier is used as the upsert key.

        Returns:
            Session: Sanitised snapshot stored in the registry without
            transient VNC token data.
        """

        async with self._lock:
            sanitized = self._sanitize_session(session)
            self._sessions[session.id] = sanitized
            return sanitized

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
            sanitized = self._sanitize_session(updated)
            self._sessions[session_id] = sanitized
            return sanitized

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
            sanitized = self._sanitize_session(updated)
            self._sessions[session_id] = sanitized
            return sanitized

    @staticmethod
    def _sanitize_session(session: Session) -> Session:
        """Remove transient VNC tokens before persisting a session snapshot.

        Args:
            session: Session instance obtained from an upstream runner or
                router handler.

        Returns:
            Session: Copy of ``session`` with ephemeral VNC token fields and
            query parameters cleared so only stable data is stored.

        Example:
            >>> SessionRegistry._sanitize_session(session)  # doctest: +SKIP
            Session(...)
        """

        details = session.vnc
        if details is None:
            return session

        sanitized_token_fields = {"token": None, "token_ttl_seconds": None}
        sanitized_http = SessionRegistry._strip_query_tokens(
            str(details.http_url) if details.http_url is not None else None
        )
        sanitized_ws = SessionRegistry._strip_query_tokens(
            str(details.websocket_url) if details.websocket_url is not None else None
        )

        if sanitized_http is not None:
            sanitized_token_fields["http_url"] = sanitized_http
        if sanitized_ws is not None:
            sanitized_token_fields["websocket_url"] = sanitized_ws

        sanitized_details = details.model_copy(update=sanitized_token_fields)
        if sanitized_details == details:
            return session

        return session.model_copy(update={"vnc": sanitized_details})

    @staticmethod
    def _strip_query_tokens(url: str | None) -> str | None:
        """Remove transient token query parameters from the provided URL.

        Args:
            url: Absolute or relative URL that may contain ``token`` query
                parameters injected during enrichment.

        Returns:
            str | None: URL without token-related query parameters or ``None``
            when ``url`` is falsy.

        Example:
            >>> SessionRegistry._strip_query_tokens(
            ...     "https://vnc/view?token=abc"
            ... )
            'https://vnc/view'
        """

        if not url:
            return None
        parsed = urlparse(url)
        filtered = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in {"token", "access_token"}
        ]
        new_query = urlencode(filtered)
        return urlunparse(parsed._replace(query=new_query))
