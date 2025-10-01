"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from core import Session, SessionProxySettings
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ..deps import get_session_registry, get_vnc_token_service
from ..deps.security import get_current_user
from ..security import AuthenticatedUser, VncTokenService
from ..services.session_registry import SessionRegistry


class TouchPayload(BaseModel):
    """Request body used to update the heartbeat timestamp for a session."""

    timestamp: datetime | None = None


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[Session])
async def list_sessions(
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[Session]:
    """Return all sessions currently tracked by the gateway."""

    return await registry.list()


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    session: Session,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Register a new session emitted by a runner."""

    enriched = session
    if session.vnc is not None and session.vnc.token is None:
        enriched = session.model_copy(
            update={
                "vnc": token_service.enrich_vnc_details(
                    session.vnc,
                    session_id=str(session.id),
                    subject=user.subject,
                )
            }
        )
    try:
        return await registry.add(enriched)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: UUID,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Return a single session by identifier."""

    try:
        return await registry.get(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Response:
    """Delete a session from the registry."""

    try:
        await registry.delete(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/proxy", response_model=Session)
async def update_proxy(
    session_id: UUID,
    payload: SessionProxySettings,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Update proxy configuration for a session."""

    try:
        return await registry.update_proxy(session_id, payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc


@router.post("/{session_id}/touch", response_model=Session)
async def touch_session(
    session_id: UUID,
    payload: TouchPayload,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Update the ``last_seen_at`` timestamp for a session."""

    try:
        return await registry.touch(session_id, timestamp=payload.timestamp)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
