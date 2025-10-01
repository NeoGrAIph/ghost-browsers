"""FastAPI entrypoint for the Runner service."""

from __future__ import annotations

from typing import Annotated
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

RunnerSettingsDep = Annotated[RunnerSettings, Depends(get_runner_settings)]
SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]


@app.get("/health", summary="Runner health probe")
async def health(settings: RunnerSettingsDep) -> dict[str, str]:
    """Return a minimal health payload consumed by gateways and tests."""

    return {
        "status": "ok",
        "runner_id": settings.runner_id,
        "camoufox_path": str(settings.camoufox_path),
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
