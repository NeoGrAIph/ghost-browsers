"""In-memory session lifecycle manager for the runner service."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import contextlib
from typing import Any
from uuid import UUID, uuid4

import anyio
from anyio.abc import TaskGroup
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

from .browser import BrowserSessionHandle, launch_browser
from .config import RunnerSettings
from .events import SessionEventPublisher
from .vnc import VncController, VncSessionHandle


class SessionCreatePayload(BaseModel):
    """Input payload accepted by :class:`SessionManager.create_session`.

    Attributes mirror :class:`core.models.Session` fields except for ``id`` and
    ``runner_id`` which are derived by the manager. Providing a ``vnc`` payload
    is optional; when omitted the manager provisions a local noVNC pipeline
    using :class:`RunnerSettings` and advertises the generated connection data.
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
        next_idle_expiry_at: Timestamp for the soonest idle timeout, if any.
        reaper_total_runs: Number of times the idle reaper executed.
        reaper_expired_sessions: Cumulative count of sessions ended by the
            idle reaper.
        reaper_last_run_at: Timestamp of the most recent reaper execution.

    Example:
        >>> SessionManagerMetrics(
        ...     active_sessions=1,
        ...     prewarm_failures=["boom"],
        ...     last_prewarm_error="boom",
        ...     next_idle_expiry_at=datetime.now(datetime.UTC),
        ...     reaper_total_runs=2,
        ...     reaper_expired_sessions=1,
        ... )
        SessionManagerMetrics(active_sessions=1, prewarm_failures=['boom'], last_prewarm_error='boom', ...)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_sessions: int = Field(default=0, ge=0)
    prewarm_failures: list[str] = Field(default_factory=list)
    last_prewarm_error: str | None = Field(default=None)
    next_idle_expiry_at: datetime | None = Field(default=None)
    reaper_total_runs: int = Field(default=0, ge=0)
    reaper_expired_sessions: int = Field(default=0, ge=0)
    reaper_last_run_at: datetime | None = Field(default=None)

    @property
    def prewarm_failure_count(self) -> int:
        """Return the number of recorded prewarm failures."""

        return len(self.prewarm_failures)


class SessionManager:
    """Manage session lifecycle and publish events for downstream consumers.

    The manager tracks sessions in-memory, publishes lifecycle events, and
    optionally runs a background reaper that enforces idle timeouts. The reaper
    interval is configurable via ``reaper_interval_seconds`` to ease testing.
    """

    def __init__(
        self,
        settings: RunnerSettings,
        event_publisher: SessionEventPublisher,
        clock: Callable[[], datetime] | None = None,
        *,
        reaper_interval_seconds: float = 1.0,
        vnc_controller: VncController | None = None,
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
        self._browser_handles: dict[UUID, BrowserSessionHandle] = {}
        self._vnc_controller = vnc_controller
        self._vnc_handles: dict[UUID, VncSessionHandle] = {}
        self._next_idle_expiry_at: datetime | None = None
        self._reaper_total_runs = 0
        self._reaper_expired_sessions = 0
        self._reaper_last_run_at: datetime | None = None
        self._reaper_interval = max(0.1, float(reaper_interval_seconds))
        self._reaper_task_group: TaskGroup | None = None

    async def create_session(self, payload: SessionCreatePayload) -> Session:
        """Create, persist, and broadcast a new session object."""

        async with self._lock:
            session_id = uuid4()
            now = self._clock()
            sanitized_vnc = self._sanitize_vnc_payload(payload.vnc)
            vnc_details, vnc_handle = await self._resolve_vnc(
                payload,
                session_id,
                sanitized_vnc=sanitized_vnc,
            )
            browser_handle: BrowserSessionHandle | None = None
            metadata = dict(payload.metadata)
            try:
                browser_handle = await launch_browser(
                    self._settings,
                    browser=payload.browser,
                    headless=payload.headless,
                    env=(
                        vnc_handle.browser_environment()
                        if vnc_handle is not None
                        else None
                    ),
                )
            except Exception:
                if browser_handle is not None:
                    await browser_handle.shutdown(force=True)
                await self._discard_vnc_handle(session_id, vnc_handle)
                raise
            if browser_handle.pid is not None:
                metadata.setdefault("runner_browser_pid", browser_handle.pid)
            vnc_enabled = (
                payload.vnc_enabled
                if payload.vnc_enabled is not None
                else (vnc_details is not None and not payload.headless)
            )
            try:
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
                    ws_endpoint=browser_handle.ws_endpoint,
                    proxy=payload.proxy,
                    vnc=vnc_details,
                    vnc_enabled=vnc_enabled,
                    metadata=metadata,
                )
            except Exception:
                await browser_handle.shutdown(force=True)
                await self._discard_vnc_handle(session_id, vnc_handle)
                raise
            self._sessions[session_id] = session
            self._browser_handles[session_id] = browser_handle
            if vnc_handle is not None:
                self._vnc_handles[session_id] = vnc_handle
            self._recalculate_next_idle_expiry_locked()
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
            if (
                update_data.get("status") is SessionStatus.DEAD
                and "ws_endpoint" not in update_data
            ):
                update_data["ws_endpoint"] = None
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
            self._recalculate_next_idle_expiry_locked()
            if self._should_cleanup_browser(existing, session):
                await self._shutdown_browser(
                    session_id, force=session.status is SessionStatus.DEAD
                )
            if self._should_cleanup_vnc(existing, session):
                await self._release_vnc_handle(session_id)
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
            ws_endpoint=None,
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
            next_idle_expiry = self._next_idle_expiry_at
            reaper_total_runs = self._reaper_total_runs
            reaper_expired_sessions = self._reaper_expired_sessions
            reaper_last_run = self._reaper_last_run_at
        return SessionManagerMetrics(
            active_sessions=active_sessions,
            prewarm_failures=failures,
            last_prewarm_error=last_error,
            next_idle_expiry_at=next_idle_expiry,
            reaper_total_runs=reaper_total_runs,
            reaper_expired_sessions=reaper_expired_sessions,
            reaper_last_run_at=reaper_last_run,
        )

    async def touch_session(self, session_id: UUID) -> Session:
        """Refresh the ``last_seen_at`` timestamp to keep the session alive.

        Args:
            session_id: Identifier of the session to update.

        Returns:
            Session: Updated session snapshot reflecting the new heartbeat.

        Example:
            >>> await manager.touch_session(session_id)  # doctest: +SKIP
        """

        return await self.update_session(
            session_id, SessionUpdatePayload(last_seen_at=self._clock())
        )

    async def reap_expired_sessions(self) -> int:
        """End sessions that exceeded their idle TTL and return the count.

        Returns:
            int: Number of sessions transitioned to ``DEAD`` during the sweep.

        Example:
            >>> await manager.reap_expired_sessions()  # doctest: +SKIP
        """

        now = self._clock()
        async with self._lock:
            expired_ids: list[UUID] = []
            next_expiry: datetime | None = None
            for session in self._sessions.values():
                if session.status is SessionStatus.DEAD:
                    continue
                candidate = session.last_seen_at + timedelta(
                    seconds=session.idle_ttl_seconds
                )
                if candidate <= now:
                    expired_ids.append(session.id)
                    continue
                if next_expiry is None or candidate < next_expiry:
                    next_expiry = candidate
            self._next_idle_expiry_at = next_expiry
            self._reaper_total_runs += 1
            self._reaper_last_run_at = now
        expired = 0
        for session_id in expired_ids:
            try:
                await self.end_session(
                    session_id,
                    reason="idle-timeout",
                    ended_at=now,
                )
            except SessionNotFoundError:  # pragma: no cover - defensive guard
                continue
            expired += 1
        if expired:
            async with self._lock:
                self._reaper_expired_sessions += expired
        return expired

    async def start(self) -> None:
        """Start the background idle reaper task if not already running.

        Example:
            >>> await manager.start()  # doctest: +SKIP
        """

        async with self._lock:
            if self._reaper_task_group is not None:
                return
            task_group = anyio.create_task_group()
            await task_group.__aenter__()
            task_group.start_soon(self._reaper_loop)
            self._reaper_task_group = task_group

    async def stop(self) -> None:
        """Stop the background idle reaper task if it is running.

        Example:
            >>> await manager.stop()  # doctest: +SKIP
        """

        async with self._lock:
            task_group = self._reaper_task_group
            self._reaper_task_group = None
        if task_group is not None:
            await task_group.__aexit__(None, None, None)
        await self._shutdown_all_vnc()

    async def _resolve_vnc(
        self,
        payload: SessionCreatePayload,
        session_id: UUID,
        *,
        sanitized_vnc: SessionVncDetails | None,
    ) -> tuple[SessionVncDetails | None, VncSessionHandle | None]:
        """Resolve VNC details and, if necessary, provision helper processes."""

        if payload.headless or not self._settings.vnc_enabled:
            return None, None
        if sanitized_vnc is not None:
            return sanitized_vnc, None
        if self._vnc_controller is None:
            return None, None
        handle = await self._vnc_controller.allocate(str(session_id))
        return handle.details, handle

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

    def _recalculate_next_idle_expiry_locked(self) -> None:
        """Recompute the nearest idle expiry using the current session map.

        Example:
            >>> manager._recalculate_next_idle_expiry_locked()  # doctest: +SKIP
        """

        next_expiry: datetime | None = None
        for session in self._sessions.values():
            if session.status is SessionStatus.DEAD:
                continue
            candidate = session.last_seen_at + timedelta(
                seconds=session.idle_ttl_seconds
            )
            if next_expiry is None or candidate < next_expiry:
                next_expiry = candidate
        self._next_idle_expiry_at = next_expiry

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

    def _should_cleanup_browser(self, previous: Session, current: Session) -> bool:
        """Return ``True`` when the stored browser handle should be terminated.

        Args:
            previous: Session snapshot prior to the update.
            current: Session snapshot after applying the update.

        Returns:
            bool: ``True`` when the associated Playwright process should be
            stopped (e.g. terminal status, endpoint cleared or changed).

        Example:
            >>> manager._should_cleanup_browser(prev, curr)  # doctest: +SKIP
            True
        """

        if previous.id != current.id:
            return False
        previous_endpoint = previous.ws_endpoint
        current_endpoint = current.ws_endpoint
        if previous_endpoint is None:
            return False
        if current.status is SessionStatus.DEAD:
            return True
        if current_endpoint is None:
            return True
        return current_endpoint != previous_endpoint

    async def _shutdown_browser(self, session_id: UUID, *, force: bool) -> None:
        """Terminate and discard the browser handle for ``session_id``.

        Args:
            session_id: Identifier of the session whose browser should be
                terminated.
            force: When ``True`` kill the process immediately; otherwise allow a
                graceful shutdown.

        Example:
            >>> await manager._shutdown_browser(session_id, force=True)  # doctest: +SKIP
        """

        handle = self._browser_handles.pop(session_id, None)
        if handle is None:
            return
        await handle.shutdown(force=force)

    async def _release_vnc_handle(self, session_id: UUID) -> None:
        """Stop helper processes backing the VNC session for ``session_id``."""

        handle = self._vnc_handles.pop(session_id, None)
        if handle is None or self._vnc_controller is None:
            return
        await self._vnc_controller.release(handle)

    async def _discard_vnc_handle(
        self, session_id: UUID, handle: VncSessionHandle | None
    ) -> None:
        """Release ``handle`` regardless of whether it was persisted."""

        if handle is None:
            return
        if session_id in self._vnc_handles:
            await self._release_vnc_handle(session_id)
            return
        if self._vnc_controller is not None:
            await self._vnc_controller.release(handle)

    async def _shutdown_all_vnc(self) -> None:
        """Terminate every tracked VNC handle during service shutdown."""

        if self._vnc_controller is None:
            self._vnc_handles.clear()
            return
        handles = list(self._vnc_handles.items())
        self._vnc_handles.clear()
        for _session_id, handle in handles:
            with contextlib.suppress(Exception):
                await self._vnc_controller.release(handle)

    def _should_cleanup_vnc(self, previous: Session, current: Session) -> bool:
        """Determine whether the stored VNC handle should be released."""

        if previous.id != current.id:
            return False
        if previous.id not in self._vnc_handles:
            return False
        if current.status is SessionStatus.DEAD:
            return True
        if current.headless:
            return True
        if current.vnc is None or not current.vnc_enabled:
            return True
        return False


    async def _reaper_loop(self) -> None:
        """Background coroutine periodically reaping idle sessions.

        Example:
            >>> await manager._reaper_loop()  # doctest: +SKIP
        """

        try:
            while True:
                await anyio.sleep(self._reaper_interval)
                await self.reap_expired_sessions()
        except BaseException:  # pragma: no cover - cancellation/propagation
            raise


__all__ = [
    "SessionCreatePayload",
    "SessionManager",
    "SessionNotFoundError",
    "SessionManagerMetrics",
    "SessionUpdatePayload",
]
