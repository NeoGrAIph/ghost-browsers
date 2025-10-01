"""FastAPI entrypoint for the Runner service."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from core.models import Session
from fastapi import Depends, FastAPI, HTTPException, status

from .config import RunnerSettings
from .dependencies import get_runner_settings, get_session_manager
from .session_manager import (
    SessionCreatePayload,
    SessionManager,
    SessionNotFoundError,
    SessionUpdatePayload,
)

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
    }


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

    return await manager.create_session(payload)


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


__all__ = ["app"]
