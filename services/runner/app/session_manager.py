"""In-memory session lifecycle manager for the runner service."""

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Mapping
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

from .browser import BrowserLaunchError, BrowserSessionHandle, launch_browser
from .browser_flags import (
    merge_browser_flags,
    normalise_browser_flags,
    requires_additional_flags,
)
from .config import RunnerSettings, WarmPoolMode
from .events import SessionEventPublisher
from .metrics import (
    ACTIVE_SESSIONS_GAUGE,
    REAPER_EXPIRED_SESSIONS_COUNTER,
    REAPER_LAST_RUN_GAUGE,
    REAPER_RUNS_COUNTER,
    SESSION_ALLOCATE_SECONDS,
    VNC_ALLOCATION_REQUESTS_COUNTER,
    VNC_ALLOCATIONS_GAUGE,
)
from .vnc import VncController, VncSessionHandle
from .warm_pool import (
    WarmPoolManager,
    WarmPoolProvisioningError,
    WarmPoolReservation,
    WarmPoolStateError,
    WarmPoolStatistics,
)


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


class SessionCapacityError(RuntimeError):
    """Raised when the runner cannot honour a session request due to capacity."""


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
        >>> metrics = SessionManagerMetrics(
        ...     active_sessions=1,
        ...     prewarm_failures=["boom"],
        ...     last_prewarm_error="boom",
        ...     next_idle_expiry_at=datetime.now(datetime.UTC),
        ...     reaper_total_runs=2,
        ...     reaper_expired_sessions=1,
        ... )
        >>> metrics.active_sessions
        1
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


@dataclass(frozen=True)
class BrowserAcquisition:
    """Aggregate details for a browser handle obtained during session setup.

    Attributes:
        handle: Browser session handle ready to be persisted.
        metadata: Metadata dictionary enriched with origin descriptors that
            explain how the browser was sourced.
        reservation: Warm pool reservation when the browser originated from a
            pre-warmed workstation, otherwise ``None`` for cold launches.
    """

    handle: BrowserSessionHandle
    metadata: dict[str, Any]
    reservation: WarmPoolReservation | None


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
        warm_pool_manager: WarmPoolManager | None = None,
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
        self._warm_pool = warm_pool_manager
        self._warm_pool_started = False
        self._warm_sessions: dict[UUID, str] = {}
        self._required_browser_flags: dict[str, str] = dict(
            settings.browser_required_flags
        )
        self._next_idle_expiry_at: datetime | None = None
        self._reaper_total_runs = 0
        self._reaper_expired_sessions = 0
        self._reaper_last_run_at: datetime | None = None
        self._reaper_interval = max(0.1, float(reaper_interval_seconds))
        self._reaper_task_group: TaskGroup | None = None
        ACTIVE_SESSIONS_GAUGE.set(0)
        VNC_ALLOCATIONS_GAUGE.set(0)
        REAPER_LAST_RUN_GAUGE.set(0)
        REAPER_RUNS_COUNTER.inc(0)
        REAPER_EXPIRED_SESSIONS_COUNTER.inc(0)
        VNC_ALLOCATION_REQUESTS_COUNTER.inc(0)

    async def create_session(self, payload: SessionCreatePayload) -> Session:
        """Create, persist, and broadcast a new session object."""

        start_time = perf_counter()
        try:
            async with self._lock:
                session_id = uuid4()
                now = self._clock()
                sanitized_vnc = self._sanitize_vnc_payload(payload.vnc)
                vnc_details, vnc_handle = await self._resolve_vnc(
                    payload,
                    session_id,
                    sanitized_vnc=sanitized_vnc,
                )
                try:
                    acquisition = await self._acquire_browser_handle(
                        payload,
                        metadata=dict(payload.metadata),
                        vnc_handle=vnc_handle,
                    )
                except Exception:
                    await self._discard_vnc_handle(session_id, vnc_handle)
                    raise
                browser_handle = acquisition.handle
                metadata = acquisition.metadata
                warm_reservation = acquisition.reservation
                workstation_id = (
                    warm_reservation.snapshot.workstation_id
                    if warm_reservation is not None
                    else None
                )
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
                    if workstation_id is not None:
                        await self._cancel_warm_reservation(workstation_id)
                    else:
                        await self._safe_shutdown_cold_browser(browser_handle)
                    await self._discard_vnc_handle(session_id, vnc_handle)
                    raise
                try:
                    if workstation_id is not None:
                        await self._mark_warm_slot_busy(workstation_id)
                except SessionCapacityError:
                    if workstation_id is not None:
                        await self._cancel_warm_reservation(workstation_id)
                    else:
                        await self._safe_shutdown_cold_browser(browser_handle)
                    await self._discard_vnc_handle(session_id, vnc_handle)
                    raise
                self._sessions[session_id] = session
                self._browser_handles[session_id] = browser_handle
                if workstation_id is not None:
                    self._warm_sessions[session_id] = workstation_id
                if vnc_handle is not None:
                    self._vnc_handles[session_id] = vnc_handle
                VNC_ALLOCATIONS_GAUGE.set(len(self._vnc_handles))
                self._recalculate_next_idle_expiry_locked()
                if session.status is not SessionStatus.DEAD:
                    self._active_sessions += 1
                    ACTIVE_SESSIONS_GAUGE.set(self._active_sessions)
                await self._publish(session, SessionEventType.CREATED, reason=None)
                return session
        finally:
            SESSION_ALLOCATE_SECONDS.observe(perf_counter() - start_time)

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
            release_warm = (
                existing.status is not SessionStatus.DEAD
                and session.status is SessionStatus.DEAD
                and session_id in self._warm_sessions
            )
            if release_warm:
                await self._release_warm_slot(session_id)
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

    def get_warm_pool_statistics(self) -> WarmPoolStatistics | None:
        """Return warm pool utilisation statistics for health reporting."""

        warm_pool = self._warm_pool
        if warm_pool is None:
            return None
        return warm_pool.get_statistics()

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
            REAPER_RUNS_COUNTER.inc()
            self._reaper_last_run_at = now
            REAPER_LAST_RUN_GAUGE.set(now.timestamp())
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
                REAPER_EXPIRED_SESSIONS_COUNTER.inc(expired)
        return expired

    async def start(self) -> None:
        """Start the background idle reaper task if not already running.

        Example:
            >>> await manager.start()  # doctest: +SKIP
        """

        if self._warm_pool is not None and not self._warm_pool_started:
            await self._warm_pool.start()
            self._warm_pool_started = True
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
        VNC_ALLOCATION_REQUESTS_COUNTER.inc()
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

    async def _acquire_browser_handle(
        self,
        payload: SessionCreatePayload,
        *,
        metadata: dict[str, Any],
        vnc_handle: VncSessionHandle | None,
    ) -> BrowserAcquisition:
        """Return a browser handle using the configured warm pool strategy.

        Args:
            payload: Request describing the desired session properties such as
                browser family and headless mode.
            metadata: Mutable copy of the session metadata derived from the
                create payload. The method augments it with origin descriptors
                before returning.
            vnc_handle: Optional VNC allocation whose environment variables are
                required when a cold browser launch occurs for visual sessions.

        Returns:
            BrowserAcquisition: Dataclass bundling the browser handle, enriched
            metadata, and a warm pool reservation when a pre-warmed workstation
            was selected.

        Raises:
            SessionCapacityError: Raised when the configuration demands a warm
                pool but it is unavailable, or when spawning a cold browser
                fails.

        Example:
            >>> acquisition = await manager._acquire_browser_handle(  # doctest: +SKIP
            ...     payload,
            ...     metadata={},
            ...     vnc_handle=None,
            ... )
            >>> acquisition.handle.ws_endpoint  # doctest: +SKIP
            'ws://camoufox/...'
        """

        effective_flags, requested_flags = self._resolve_browser_flags(metadata)
        if effective_flags:
            metadata["browser_flags"] = dict(effective_flags)
        else:
            metadata.pop("browser_flags", None)
        custom_flags_requested = requires_additional_flags(
            requested_flags, self._required_browser_flags
        )

        mode = self._settings.warm_pool_mode
        if mode is WarmPoolMode.COLD_ONLY or custom_flags_requested:
            if mode is WarmPoolMode.WARM_ONLY:
                raise SessionCapacityError(
                    "warm pool cannot satisfy requested browser flags"
                )
            metadata.pop("warm_pool", None)
            handle = await self._launch_cold_browser(
                payload,
                vnc_handle=vnc_handle,
                browser_flags=effective_flags,
            )
            metadata = self._inject_browser_origin(
                metadata,
                kind="cold_launch",
                details={
                    "reason": "mode-cold-only"
                    if mode is WarmPoolMode.COLD_ONLY
                    else "custom-browser-flags",
                },
            )
            return BrowserAcquisition(handle=handle, metadata=metadata, reservation=None)

        warm_pool = self._warm_pool
        if warm_pool is not None:
            try:
                reservation = await self._reserve_warm_slot(metadata)
            except SessionCapacityError:
                if mode is WarmPoolMode.WARM_ONLY:
                    raise
            else:
                details = {
                    "workstation_id": reservation.snapshot.workstation_id,
                }
                if reservation.snapshot.fingerprint_id is not None:
                    details["fingerprint_id"] = reservation.snapshot.fingerprint_id
                metadata = self._merge_warm_pool_metadata(metadata, reservation)
                metadata = self._inject_browser_origin(
                    metadata,
                    kind="warm_pool",
                    details=details,
                )
                return BrowserAcquisition(
                    handle=reservation.handle,
                    metadata=metadata,
                    reservation=reservation,
                )
        elif mode is WarmPoolMode.WARM_ONLY:
            raise SessionCapacityError("warm pool is not configured")

        metadata.pop("warm_pool", None)
        reason = "warm-pool-disabled" if warm_pool is None else "warm-pool-unavailable"
        handle = await self._launch_cold_browser(
            payload,
            vnc_handle=vnc_handle,
            browser_flags=effective_flags,
        )
        metadata = self._inject_browser_origin(
            metadata,
            kind="cold_launch",
            details={"reason": reason},
        )
        return BrowserAcquisition(handle=handle, metadata=metadata, reservation=None)

    async def _launch_cold_browser(
        self,
        payload: SessionCreatePayload,
        *,
        vnc_handle: VncSessionHandle | None,
        browser_flags: Mapping[str, str] | None,
    ) -> BrowserSessionHandle:
        """Launch a fresh Playwright browser outside of the warm pool.

        Args:
            payload: Session creation request containing browser preferences.
            vnc_handle: Optional handle providing environment variables (e.g.
                ``DISPLAY``) required for non-headless sessions.
            browser_flags: Mapping of Camoufox/Firefox flags that should be
                injected into the environment prior to launching Playwright.

        Returns:
            BrowserSessionHandle: Handle referencing the running Playwright
            process.

        Raises:
            SessionCapacityError: If Playwright cannot be launched successfully.

        Example:
            >>> handle = await manager._launch_cold_browser(  # doctest: +SKIP
            ...     payload,
            ...     vnc_handle=None,
            ... )
            >>> handle.ws_endpoint  # doctest: +SKIP
            'ws://camoufox/...'
        """

        env: dict[str, str] = {}
        if vnc_handle is not None:
            env.update(vnc_handle.browser_environment())
        try:
            return await launch_browser(
                self._settings,
                browser=payload.browser,
                headless=payload.headless,
                env=env or None,
                browser_flags=browser_flags or None,
            )
        except BrowserLaunchError as exc:
            raise SessionCapacityError("failed to launch browser process") from exc

    def _resolve_browser_flags(
        self, metadata: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Return merged and requested browser flags for ``metadata``.

        Args:
            metadata: Mutable session metadata supplied during creation.

        Returns:
            tuple[dict[str, str], dict[str, str]]: A pair where the first
            element contains the merged (required + requested) flags and the
            second element contains only the requested overrides supplied by the
            caller.

        Example:
            >>> manager._resolve_browser_flags({"browser_flags": {"X": "1"}})  # doctest: +SKIP
            ({'X': '1'}, {'X': '1'})
        """

        requested_raw = metadata.get("browser_flags")
        requested = (
            normalise_browser_flags(requested_raw)
            if isinstance(requested_raw, Mapping)
            else {}
        )
        merged = merge_browser_flags(self._required_browser_flags, requested)
        return merged, requested

    def _inject_browser_origin(
        self,
        metadata: dict[str, Any],
        *,
        kind: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Attach metadata describing how the browser was provisioned.

        Args:
            metadata: Session metadata dictionary to update in-place.
            kind: Human-readable label identifying the browser origin.
            details: Optional mapping providing additional context such as
                fallback reasons or workstation identifiers.

        Returns:
            dict[str, Any]: The mutated metadata dictionary for chaining.

        Example:
            >>> manager._inject_browser_origin({}, kind="cold_launch")  # doctest: +SKIP
            {'browser_origin': {'kind': 'cold_launch', 'mode': 'hybrid'}}
        """

        descriptor: dict[str, Any] = {
            "kind": kind,
            "mode": self._settings.warm_pool_mode.value,
        }
        if details:
            descriptor.update(details)
        existing = metadata.get("browser_origin")
        if isinstance(existing, dict):
            metadata["browser_origin"] = {**existing, **descriptor}
        else:
            metadata["browser_origin"] = descriptor
        return metadata

    async def _safe_shutdown_cold_browser(self, handle: BrowserSessionHandle) -> None:
        """Terminate a cold-launched browser that was not persisted.

        Args:
            handle: Browser handle obtained from :func:`launch_browser`.

        Example:
            >>> await manager._safe_shutdown_cold_browser(handle)  # doctest: +SKIP
        """

        with contextlib.suppress(Exception):
            await handle.shutdown(force=True)

    async def _reserve_warm_slot(
        self, metadata: dict[str, Any]
    ) -> WarmPoolReservation:
        """Reserve a warm workstation slot for a new session.

        Args:
            metadata: Metadata dictionary supplied during session creation.

        Returns:
            WarmPoolReservation: Snapshot and handle representing the reserved
            workstation.

        Raises:
            SessionCapacityError: If warm pool support is disabled or no idle
                slots are available.

        Example:
            >>> await manager._reserve_warm_slot({})  # doctest: +SKIP
        """

        if self._warm_pool is None:
            raise SessionCapacityError("warm pool is not configured")
        if not self._warm_pool_started:
            await self._warm_pool.start()
            self._warm_pool_started = True
        requested = self._extract_requested_workstation(metadata)
        try:
            return await self._warm_pool.reserve_slot(requested)
        except WarmPoolStateError as exc:  # pragma: no cover - defensive guard
            raise SessionCapacityError("no warm workstations available") from exc

    def _extract_requested_workstation(self, metadata: dict[str, Any]) -> str | None:
        """Return a workstation identifier requested via metadata.

        Args:
            metadata: Metadata payload supplied by the API caller.

        Returns:
            str | None: Identifier of the requested workstation when provided,
            otherwise ``None``.

        Example:
            >>> manager._extract_requested_workstation(  # doctest: +SKIP
            ...     {"warm_pool": {"workstation_id": "ws-1"}}
            ... )
            'ws-1'
        """

        warm_hint = metadata.get("warm_pool")
        if isinstance(warm_hint, dict):
            value = warm_hint.get("workstation_id")
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
        return None

    def _merge_warm_pool_metadata(
        self, metadata: dict[str, Any], reservation: WarmPoolReservation
    ) -> dict[str, Any]:
        """Return ``metadata`` augmented with warm pool descriptors.

        Args:
            metadata: Base metadata cloned from the create payload.
            reservation: Reservation carrying snapshot and launch environment
                for the warm workstation.

        Returns:
            dict[str, Any]: Metadata dictionary enriched with a ``warm_pool``
            section describing the allocated workstation.

        Example:
            >>> manager._merge_warm_pool_metadata({}, reservation)  # doctest: +SKIP
        """

        warm_metadata = {
            "workstation_id": reservation.snapshot.workstation_id,
            "fingerprint_id": reservation.snapshot.fingerprint_id,
            "proxy_url": reservation.snapshot.proxy_url,
            "launch_env": dict(reservation.environment),
        }
        existing = metadata.get("warm_pool")
        if isinstance(existing, dict):
            metadata["warm_pool"] = {**existing, **warm_metadata}
        else:
            metadata["warm_pool"] = warm_metadata
        return metadata

    async def _cancel_warm_reservation(self, workstation_id: str) -> None:
        """Rollback a reserved warm slot back to ``idle`` state.

        Args:
            workstation_id: Identifier of the reserved workstation to release.

        Example:
            >>> await manager._cancel_warm_reservation("ws-1")  # doctest: +SKIP
        """

        if self._warm_pool is None:
            return
        with contextlib.suppress(WarmPoolStateError):
            await self._warm_pool.cancel_reservation(workstation_id)

    async def _mark_warm_slot_busy(self, workstation_id: str) -> None:
        """Transition a reserved warm slot into the ``busy`` state.

        Args:
            workstation_id: Identifier of the reserved workstation.

        Raises:
            SessionCapacityError: If the reservation vanished before it could be
                marked busy.

        Example:
            >>> await manager._mark_warm_slot_busy("ws-1")  # doctest: +SKIP
        """

        if self._warm_pool is None:
            raise SessionCapacityError("warm pool is not configured")
        try:
            await self._warm_pool.mark_busy(workstation_id)
        except WarmPoolStateError as exc:
            raise SessionCapacityError(
                f"warm workstation '{workstation_id}' is no longer reserved"
            ) from exc

    async def _release_warm_slot(self, session_id: UUID) -> None:
        """Recycle the warm slot associated with ``session_id``.

        Args:
            session_id: Identifier of the session whose workstation should be
                recycled.

        Raises:
            WarmPoolProvisioningError: Propagated when the recycle process fails
                to provision a fresh workstation.

        Example:
            >>> await manager._release_warm_slot(session_id)  # doctest: +SKIP
        """

        if self._warm_pool is None:
            return
        workstation_id = self._warm_sessions.pop(session_id, None)
        if workstation_id is None:
            return
        try:
            await self._warm_pool.release_slot(workstation_id)
        except WarmPoolProvisioningError as exc:
            message = str(exc)
            self._prewarm_failures.append(message)
            self._last_prewarm_error = message
            raise

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
        ACTIVE_SESSIONS_GAUGE.set(self._active_sessions)

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

        warm_managed = session_id in self._warm_sessions
        handle = self._browser_handles.pop(session_id, None)
        if handle is None:
            return
        if warm_managed:
            return
        await handle.shutdown(force=force)

    async def _release_vnc_handle(self, session_id: UUID) -> None:
        """Stop helper processes backing the VNC session for ``session_id``."""

        handle = self._vnc_handles.pop(session_id, None)
        if handle is None or self._vnc_controller is None:
            return
        await self._vnc_controller.release(handle)
        VNC_ALLOCATIONS_GAUGE.set(len(self._vnc_handles))

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
        VNC_ALLOCATIONS_GAUGE.set(len(self._vnc_handles))

    async def _shutdown_all_vnc(self) -> None:
        """Terminate every tracked VNC handle during service shutdown."""

        if self._vnc_controller is None:
            self._vnc_handles.clear()
            VNC_ALLOCATIONS_GAUGE.set(0)
            return
        handles = list(self._vnc_handles.items())
        self._vnc_handles.clear()
        for _session_id, handle in handles:
            with contextlib.suppress(Exception):
                await self._vnc_controller.release(handle)
        VNC_ALLOCATIONS_GAUGE.set(0)

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
    "SessionCapacityError",
    "SessionNotFoundError",
    "SessionManagerMetrics",
    "SessionUpdatePayload",
]
