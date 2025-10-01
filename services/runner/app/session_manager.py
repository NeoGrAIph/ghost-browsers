"""In-memory session lifecycle manager for the runner service."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import anyio
from core.models import (
    Session,
    SessionEvent,
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
    StartUrlWait,
)
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, PositiveInt

from .config import RunnerSettings
from .events import SessionEventPublisher


class SessionCreatePayload(BaseModel):
    """Input payload accepted by :class:`SessionManager.create_session`.

    Attributes mirror :class:`core.models.Session` fields except for ``id`` and
    ``runner_id`` which are derived by the manager. Providing a ``vnc`` payload
    is optional; when omitted the manager constructs a stub value based on
    :class:`RunnerSettings`.
    """

    model_config = ConfigDict(extra="forbid")

    status: SessionStatus = Field(default=SessionStatus.INIT)
    headless: bool = Field(default=False)
    idle_ttl_seconds: PositiveInt = Field(default=300, ge=30, le=3600)
    start_url: AnyUrl | None = Field(default=None)
    start_url_wait: StartUrlWait = Field(default=StartUrlWait.LOAD)
    browser: str = Field(default="camoufox", min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    ws_endpoint: str | None = Field(default=None)
    proxy: SessionProxySettings | None = Field(default=None)
    vnc: SessionVncDetails | None = Field(default=None)
    vnc_enabled: bool | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionUpdatePayload(BaseModel):
    """Partial update applied to an existing session."""

    model_config = ConfigDict(extra="forbid")

    status: SessionStatus | None = Field(default=None)
    last_seen_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)
    headless: bool | None = Field(default=None)
    idle_ttl_seconds: PositiveInt | None = Field(default=None, ge=30, le=3600)
    start_url: AnyUrl | None = Field(default=None)
    start_url_wait: StartUrlWait | None = Field(default=None)
    browser: str | None = Field(default=None, min_length=1)
    labels: dict[str, str] | None = Field(default=None)
    ws_endpoint: str | None = Field(default=None)
    proxy: SessionProxySettings | None = Field(default=None)
    vnc: SessionVncDetails | None = Field(default=None)
    vnc_enabled: bool | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)
    reason: str | None = Field(default=None)


class SessionNotFoundError(KeyError):
    """Raised when attempting to operate on an unknown session identifier."""


class SessionManagerMetrics(BaseModel):
    """Snapshot of operational counters maintained by :class:`SessionManager`.

    Attributes:
        active_sessions: Number of sessions that are not in the ``DEAD`` state.
        prewarm_failures: Ordered list of recorded prewarm failure messages.
        last_prewarm_error: Most recent prewarm failure message, if any.

    Example:
        >>> SessionManagerMetrics(
        ...     active_sessions=1,
        ...     prewarm_failures=["boom"],
        ...     last_prewarm_error="boom",
        ... )
        SessionManagerMetrics(active_sessions=1, prewarm_failures=['boom'], last_prewarm_error='boom')
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_sessions: int = Field(default=0, ge=0)
    prewarm_failures: list[str] = Field(default_factory=list)
    last_prewarm_error: str | None = Field(default=None)

    @property
    def prewarm_failure_count(self) -> int:
        """Return the number of recorded prewarm failures."""

        return len(self.prewarm_failures)


class SessionManager:
    """Manage session lifecycle and publish events for downstream consumers."""

    def __init__(
        self,
        settings: RunnerSettings,
        event_publisher: SessionEventPublisher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._publisher = event_publisher
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sessions: dict[UUID, Session] = {}
        self._lock = anyio.Lock()
        self._active_sessions = 0
        self._prewarm_failures: deque[str] = deque(
            maxlen=settings.prewarm_failure_history_size
        )
        self._last_prewarm_error: str | None = None

    async def create_session(self, payload: SessionCreatePayload) -> Session:
        """Create, persist, and broadcast a new session object."""

        async with self._lock:
            session_id = uuid4()
            now = self._clock()
            sanitized_vnc = self._sanitize_vnc_payload(payload.vnc)
            vnc_details = self._resolve_vnc(
                payload, session_id, sanitized_vnc=sanitized_vnc
            )
            vnc_enabled = (
                payload.vnc_enabled
                if payload.vnc_enabled is not None
                else (vnc_details is not None and not payload.headless)
            )
            session = Session(
                id=session_id,
                runner_id=self._settings.runner_id,
                status=payload.status,
                created_at=now,
                last_seen_at=now,
                headless=payload.headless,
                idle_ttl_seconds=payload.idle_ttl_seconds,
                start_url=payload.start_url,
                start_url_wait=payload.start_url_wait,
                browser=payload.browser,
                labels=payload.labels,
                ws_endpoint=payload.ws_endpoint,
                proxy=payload.proxy,
                vnc=vnc_details,
                vnc_enabled=vnc_enabled,
                metadata=payload.metadata,
            )
            self._sessions[session_id] = session
            if session.status is not SessionStatus.DEAD:
                self._active_sessions += 1
            await self._publish(session, SessionEventType.CREATED, reason=None)
            return session

    async def update_session(self, session_id: UUID, payload: SessionUpdatePayload) -> Session:
        """Apply a partial update to a stored session and broadcast the change."""

        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            existing = self._sessions[session_id]
            update_data = payload.model_dump(exclude_unset=True)
            if "vnc" in update_data:
                update_data["vnc"] = self._sanitize_vnc_payload(payload.vnc)
            reason = update_data.pop("reason", None)
            merged_labels = update_data.pop("labels", None)
            merged_metadata = update_data.pop("metadata", None)
            if "last_seen_at" not in update_data:
                update_data["last_seen_at"] = self._clock()
            if (
                update_data.get("status") is SessionStatus.DEAD
                and update_data.get("ended_at") is None
            ):
                update_data["ended_at"] = self._clock()
            if merged_labels is not None:
                update_data["labels"] = {**existing.labels, **merged_labels}
            if merged_metadata is not None:
                update_data["metadata"] = {**existing.metadata, **merged_metadata}
            session = existing.model_copy(update=update_data, deep=True)
            self._sessions[session_id] = session
            self._recalculate_active_sessions(existing.status, session.status)
            event_type = (
                SessionEventType.ENDED
                if session.status is SessionStatus.DEAD
                else SessionEventType.UPDATED
            )
            await self._publish(session, event_type, reason=reason)
            return session

    async def end_session(
        self,
        session_id: UUID,
        *,
        reason: str | None = None,
        ended_at: datetime | None = None,
    ) -> Session:
        """Mark a session as terminated and emit a terminal event."""

        payload = SessionUpdatePayload(
            status=SessionStatus.DEAD,
            ended_at=ended_at,
            vnc_enabled=False,
            reason=reason,
            vnc=None,
        )
        return await self.update_session(session_id, payload)

    async def get_session(self, session_id: UUID) -> Session:
        """Return the current snapshot for ``session_id``."""

        async with self._lock:
            if session_id not in self._sessions:
                raise SessionNotFoundError(session_id)
            return self._sessions[session_id]

    async def list_sessions(self) -> list[Session]:
        """Return all tracked sessions ordered by insertion time."""

        async with self._lock:
            return list(self._sessions.values())

    async def record_prewarm_failure(self, message: str) -> None:
        """Append ``message`` to the rolling prewarm failure history."""

        async with self._lock:
            self._prewarm_failures.append(message)
            self._last_prewarm_error = message

    async def reset_prewarm_failures(self) -> None:
        """Clear recorded prewarm failures, typically after a successful run."""

        async with self._lock:
            self._prewarm_failures.clear()
            self._last_prewarm_error = None

    async def get_metrics(self) -> SessionManagerMetrics:
        """Return a metrics snapshot safe to expose via diagnostics endpoints."""

        async with self._lock:
            active_sessions = self._active_sessions
            failures = list(self._prewarm_failures)
            last_error = self._last_prewarm_error
        return SessionManagerMetrics(
            active_sessions=active_sessions,
            prewarm_failures=failures,
            last_prewarm_error=last_error,
        )

    def _resolve_vnc(
        self,
        payload: SessionCreatePayload,
        session_id: UUID,
        *,
        sanitized_vnc: SessionVncDetails | None,
    ) -> SessionVncDetails | None:
        """Return VNC details honouring payload overrides and settings defaults."""

        if payload.headless or not self._settings.vnc_enabled:
            return None
        if sanitized_vnc is not None:
            return sanitized_vnc
        return SessionVncDetails(
            http_url=f"{self._settings.vnc_http_base_url}/{session_id}",
            websocket_url=f"{self._settings.vnc_ws_base_url}/{session_id}",
            token=None,
            token_ttl_seconds=None,
        )

    def _sanitize_vnc_payload(
        self, details: SessionVncDetails | None
    ) -> SessionVncDetails | None:
        """Strip runner-controlled VNC tokens so the gateway can re-sign them.

        Args:
            details: Raw VNC descriptor supplied via create or update payloads.

        Returns:
            SessionVncDetails | None: Either the original descriptor when no
            token metadata is present or a copy with ``token`` and
            ``token_ttl_seconds`` cleared, ensuring that downstream services are
            responsible for issuing signatures.

        Example:
            Runner-supplied descriptors containing ``token="abc"`` and
            ``token_ttl_seconds=30`` are returned with both values cleared so that
            downstream gateways can inject fresh credentials.
        """

        if details is None:
            return None
        if details.token is None and details.token_ttl_seconds is None:
            return details
        return details.model_copy(update={"token": None, "token_ttl_seconds": None})

    def _recalculate_active_sessions(
        self, previous_status: SessionStatus, current_status: SessionStatus
    ) -> None:
        """Update the active session counter based on a status transition."""

        was_active = previous_status is not SessionStatus.DEAD
        is_active = current_status is not SessionStatus.DEAD
        if was_active and not is_active:
            self._active_sessions = max(0, self._active_sessions - 1)
        elif not was_active and is_active:
            self._active_sessions += 1

    async def _publish(
        self,
        session: Session,
        event_type: SessionEventType,
        *,
        reason: str | None,
    ) -> None:
        """Send a :class:`SessionEvent` via the configured publisher."""

        event = SessionEvent(
            session=session,
            type=event_type,
            occurred_at=self._clock(),
            reason=reason,
        )
        await self._publisher.publish(event)


__all__ = [
    "SessionCreatePayload",
    "SessionManager",
    "SessionNotFoundError",
    "SessionManagerMetrics",
    "SessionUpdatePayload",
]
