"""FastAPI entrypoint for the Runner service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from core.models import (
    Session,
    WorkstationEvent,
    WorkstationEventType,
    WorkstationMeta,
    WorkstationState,
)
from fastapi import Depends, FastAPI, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import RunnerSettings
from .dependencies import (
    get_runner_settings,
    get_session_manager,
    get_warm_pool_manager,
    get_workstation_event_publisher,
)
from .metrics import METRICS_REGISTRY
from .session_manager import (
    SessionCreatePayload,
    SessionCapacityError,
    SessionManager,
    SessionNotFoundError,
    SessionUpdatePayload,
)
from .warm_pool import WarmPoolManager, WarmPoolSnapshot, WarmPoolState, WarmPoolStateError
from .events import WorkstationEventPublisher
from pydantic import BaseModel, Field

app = FastAPI(title="Ghost Browsers Runner", version="0.1.0")


def _normalise_base_url(url: Any | None) -> str | None:
    """Return a stable string representation for optional base URLs.

    ``AnyUrl`` instances produced by Pydantic append a trailing slash when the
    original value contains no path segment. The health endpoint should return
    URLs exactly as operators configured them, therefore this helper trims the
    extra slash only when the underlying path is empty.

    Args:
        url: Value received from the settings model.

    Returns:
        str | None: ``None`` when no URL is configured, otherwise the
        normalised textual representation.

    Example:
        >>> _normalise_base_url("http://proxy:3128/")
        'http://proxy:3128'
    """

    if url is None:
        return None

    text = str(url)
    path = getattr(url, "path", "")
    if text.endswith("/") and path in {"", "/"}:
        return text[:-1]
    return text

RunnerSettingsDep = Annotated[RunnerSettings, Depends(get_runner_settings)]
SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]
WarmPoolManagerDep = Annotated[WarmPoolManager, Depends(get_warm_pool_manager)]
WorkstationEventPublisherDep = Annotated[
    WorkstationEventPublisher, Depends(get_workstation_event_publisher)
]

_WARM_TO_PUBLIC_STATE: dict[WarmPoolState, WorkstationState] = {
    WarmPoolState.IDLE: WorkstationState.AVAILABLE,
    WarmPoolState.RESERVED: WorkstationState.PROVISIONING,
    WarmPoolState.BUSY: WorkstationState.ASSIGNED,
    WarmPoolState.RECYCLING: WorkstationState.PROVISIONING,
    WarmPoolState.DRAINING: WorkstationState.UNAVAILABLE,
    WarmPoolState.ERROR: WorkstationState.UNAVAILABLE,
}


def _isoformat_or_none(value: datetime | None) -> str | None:
    """Return an ISO formatted timestamp or ``None`` when absent.

    Args:
        value: Timestamp sourced from metrics.

    Returns:
        str | None: ISO-8601 representation or ``None``.

    Example:
        >>> _isoformat_or_none(datetime(2024, 1, 1))
        '2024-01-01T00:00:00'
    """

    if value is None:
        return None
    return value.isoformat()


def _serialise_snapshot(snapshot: WarmPoolSnapshot) -> dict[str, Any]:
    """Return a JSON payload describing the warm workstation snapshot."""

    return {
        "workstation_id": snapshot.workstation_id,
        "fingerprint_id": snapshot.fingerprint_id,
        "proxy_url": snapshot.proxy_url,
        "state": snapshot.state.value,
    }


def _translate_state_error(exc: WarmPoolStateError) -> HTTPException:
    """Translate warm pool state errors into FastAPI HTTP exceptions."""

    message = str(exc)
    lowered = message.lower()
    status_code = status.HTTP_409_CONFLICT
    if "unknown workstation" in lowered:
        status_code = status.HTTP_404_NOT_FOUND
    return HTTPException(status_code=status_code, detail=message)


def _build_workstation_meta(
    snapshot: WarmPoolSnapshot,
    *,
    metadata: dict[str, Any] | None = None,
) -> WorkstationMeta:
    """Construct :class:`WorkstationMeta` for event payloads."""

    merged_metadata: dict[str, Any] = {}
    if metadata:
        merged_metadata.update(metadata)
    if snapshot.proxy_url:
        merged_metadata.setdefault("proxy_url", snapshot.proxy_url)
    fingerprint = snapshot.fingerprint_id or "unknown"
    return WorkstationMeta(
        id=snapshot.workstation_id,
        fingerprint_id=fingerprint,
        state=_WARM_TO_PUBLIC_STATE.get(snapshot.state, WorkstationState.UNAVAILABLE),
        proxy_summary=snapshot.proxy_url,
        metadata=merged_metadata,
    )


async def _publish_workstation_event(
    publisher: WorkstationEventPublisher,
    snapshot: WarmPoolSnapshot,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
    event_type: WorkstationEventType = WorkstationEventType.UPDATED,
) -> None:
    """Publish a workstation lifecycle event through ``publisher``."""

    event = WorkstationEvent(
        type=event_type,
        workstation=_build_workstation_meta(snapshot, metadata=metadata),
        occurred_at=datetime.now(UTC),
        reason=reason,
    )
    await publisher.publish(event)


class WorkstationReservationRequest(BaseModel):
    """Input model used by :func:`reserve_workstation`."""

    workstation_id: str | None = Field(
        default=None,
        description="Identifier of the workstation to reserve when specified.",
    )


@app.get("/health", summary="Runner health probe")
async def health(
    settings: RunnerSettingsDep, manager: SessionManagerDep
) -> dict[str, Any]:
    """Return a structured health payload consumed by gateways and tests."""

    metrics = await manager.get_metrics()
    active_slots = metrics.active_sessions
    total_slots = settings.slot_limit
    available_slots = max(total_slots - active_slots, 0)
    return {
        "status": "ok",
        "runner_id": settings.runner_id,
        "camoufox_path": str(settings.camoufox_path),
        "slots": {
            "total": total_slots,
            "active": active_slots,
            "available": available_slots,
        },
        "vnc": {
            "http_base_url": str(settings.vnc_http_base_url),
            "ws_base_url": str(settings.vnc_ws_base_url),
            "enabled": settings.vnc_enabled,
        },
        "proxy": {
            "enabled": settings.proxy_enabled,
            "http_base_url": _normalise_base_url(settings.proxy_http_base_url),
            "https_base_url": _normalise_base_url(settings.proxy_https_base_url),
            "socks_base_url": _normalise_base_url(settings.proxy_socks_base_url),
        },
        "prewarm": {
            "failures": metrics.prewarm_failure_count,
            "last_error": metrics.last_prewarm_error,
        },
        "ttl": {
            "next_expiry_at": _isoformat_or_none(metrics.next_idle_expiry_at),
            "reaper": {
                "total_runs": metrics.reaper_total_runs,
                "expired_sessions": metrics.reaper_expired_sessions,
                "last_run_at": _isoformat_or_none(metrics.reaper_last_run_at),
            },
        },
    }


@app.get("/workstations", summary="List warm workstation slots")
async def list_workstations(manager: WarmPoolManagerDep) -> list[dict[str, Any]]:
    """Return snapshots describing all configured warm workstations."""

    return [_serialise_snapshot(snapshot) for snapshot in manager.list_slots()]


@app.post(
    "/workstations/reserve",
    summary="Reserve an idle workstation",
)
async def reserve_workstation(
    payload: WorkstationReservationRequest,
    warm_pool: WarmPoolManagerDep,
    publisher: WorkstationEventPublisherDep,
) -> dict[str, Any]:
    """Reserve a warm workstation slot and publish an event."""

    try:
        reservation = await warm_pool.reserve_slot(payload.workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    snapshot = reservation.snapshot
    environment = dict(reservation.environment)
    await _publish_workstation_event(
        publisher,
        snapshot,
        reason="reserved",
        metadata={"launch_env": environment},
    )
    return {
        "snapshot": _serialise_snapshot(snapshot),
        "environment": environment,
    }


@app.post(
    "/workstations/{workstation_id}/busy",
    summary="Mark a reserved workstation as busy",
)
async def mark_workstation_busy(
    workstation_id: str,
    warm_pool: WarmPoolManagerDep,
    publisher: WorkstationEventPublisherDep,
) -> dict[str, Any]:
    """Transition ``workstation_id`` from reserved to busy state."""

    try:
        snapshot = await warm_pool.mark_busy(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    await _publish_workstation_event(
        publisher,
        snapshot,
        reason="busy",
    )
    return {"snapshot": _serialise_snapshot(snapshot)}


@app.post(
    "/workstations/{workstation_id}/cancel",
    summary="Cancel a workstation reservation",
)
async def cancel_workstation_reservation(
    workstation_id: str,
    warm_pool: WarmPoolManagerDep,
    publisher: WorkstationEventPublisherDep,
) -> dict[str, Any]:
    """Return ``workstation_id`` to idle when reservation setup fails."""

    try:
        snapshot = await warm_pool.cancel_reservation(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    await _publish_workstation_event(
        publisher,
        snapshot,
        reason="cancelled",
    )
    return {"snapshot": _serialise_snapshot(snapshot)}


@app.post(
    "/workstations/{workstation_id}/release",
    summary="Release a busy workstation",
)
async def release_workstation(
    workstation_id: str,
    warm_pool: WarmPoolManagerDep,
    publisher: WorkstationEventPublisherDep,
) -> dict[str, Any]:
    """Recycle ``workstation_id`` back to the idle pool and emit an event."""

    try:
        snapshot = await warm_pool.release_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    await _publish_workstation_event(
        publisher,
        snapshot,
        reason="released",
        event_type=WorkstationEventType.RELEASED,
    )
    return {"snapshot": _serialise_snapshot(snapshot)}


@app.post(
    "/sessions",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
)
async def create_session(
    payload: SessionCreatePayload,
    manager: SessionManagerDep,
) -> Session:
    """Create a session and emit a ``session.created`` event."""

    try:
        return await manager.create_session(payload)
    except SessionCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="no warm workstations available",
        ) from exc


@app.patch("/sessions/{session_id}", response_model=Session, summary="Update a session")
async def update_session(
    session_id: UUID,
    payload: SessionUpdatePayload,
    manager: SessionManagerDep,
) -> Session:
    """Apply a partial update to an existing session."""

    try:
        return await manager.update_session(session_id, payload)
    except SessionNotFoundError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        ) from exc


@app.post(
    "/sessions/{session_id}/touch",
    response_model=Session,
    summary="Touch a session",
)
async def touch_session(session_id: UUID, manager: SessionManagerDep) -> Session:
    """Refresh the heartbeat for ``session_id`` to extend its idle TTL."""

    try:
        return await manager.touch_session(session_id)
    except SessionNotFoundError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        ) from exc


@app.delete("/sessions/{session_id}", response_model=Session, summary="Terminate a session")
async def delete_session(
    session_id: UUID,
    manager: SessionManagerDep,
) -> Session:
    """Terminate the target session and emit a ``session.ended`` event."""

    try:
        return await manager.end_session(session_id)
    except SessionNotFoundError as exc:  # pragma: no cover - defensive branch
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        ) from exc


@app.get("/metrics", summary="Prometheus metrics")
async def metrics() -> Response:
    """Expose service metrics for Prometheus scrapers."""

    payload = generate_latest(METRICS_REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def _on_startup() -> None:
    """Initialise background services such as the idle reaper."""

    await get_session_manager().start()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    """Tear down background tasks before process exit."""

    await get_session_manager().stop()


__all__ = ["app"]
