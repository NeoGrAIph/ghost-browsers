"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from core import Runner, Session, SessionProxySettings
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ..deps import (
    get_runner_client,
    get_runner_registry,
    get_session_registry,
    get_vnc_token_service,
)
from ..deps.security import get_current_user
from ..security import AuthenticatedUser, VncTokenService
from ..models.session_launch import SessionLaunchPayload
from ..services.runner_client import RunnerClientError, RunnerControlClient
from ..services.runner_registry import RunnerRegistry
from ..services.session_registry import SessionRegistry
from ..services.vnc_overrides import apply_vnc_overrides


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


@router.post("/register", response_model=Session, status_code=status.HTTP_201_CREATED)
async def register_session(
    session: Session,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Register a new session emitted by a runner."""

    runner = await runners.get(session.runner_id)
    enriched = _enrich_session(session, runner, token_service, user)
    try:
        return await registry.add(enriched)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def launch_session(
    payload: SessionLaunchPayload,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    runner_client: Annotated[RunnerControlClient, Depends(get_runner_client)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Create a session on a runner and persist it in the registry."""

    runner = await _select_runner(runners)
    try:
        session = await runner_client.create_session(runner, payload)
    except RunnerClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    enriched = _enrich_session(session, runner, token_service, user)
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


def _enrich_session(
    session: Session,
    runner: Runner | None,
    token_service: VncTokenService,
    user: AuthenticatedUser,
) -> Session:
    """Attach VNC overrides and short-lived tokens to a session payload.

    The beta gateway rewrites runner-reported VNC URLs so that all previews are
    served via a shared ingress controller instead of exposing per-session
    ports.  This helper mirrors that behaviour by applying runner-scoped
    override templates and adding gateway-issued access tokens when absent.
    """

    details = session.vnc
    if runner is not None:
        details = apply_vnc_overrides(runner, details, session_id=str(session.id))

    if details is None:
        return session

    if details.token is None:
        details = token_service.enrich_vnc_details(
            details,
            session_id=str(session.id),
            subject=user.subject,
        )

    if details is session.vnc:
        return session

    return session.model_copy(update={"vnc": details})


async def _select_runner(registry: RunnerRegistry) -> Runner:
    """Pick a runner that can accept a new session request.

    The selector prefers runners that advertise free slots via
    ``available_slots``. When all runners appear saturated we fall back to the
    first entry, allowing the runner to decide whether it can queue the
    request.
    """

    runners = await registry.list()
    if not runners:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No runners are registered",
        )

    for runner in runners:
        if runner.available_slots is None or runner.available_slots > 0:
            return runner

    return runners[0]
