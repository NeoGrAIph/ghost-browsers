"""Session management endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Iterable
from typing import Annotated
from uuid import UUID

from core import (
    AbstractSessionEventBridge,
    Runner,
    Session,
    SessionEvent,
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ..deps import (
    get_event_bridge,
    get_runner_command_client,
    get_runner_registry,
    get_session_registry,
    get_vnc_token_service,
)
from ..deps.security import get_current_user
from ..security import AuthenticatedUser, VncTokenService
from ..services.runner_client import (
    RunnerCommandClient,
    RunnerCommandError,
    SessionCreateCommand,
    SessionUpdateCommand,
)
from ..services.runner_registry import RunnerRegistry
from ..services.session_registry import SessionRegistry
from ..services.vnc_overrides import apply_vnc_overrides


class TouchPayload(BaseModel):
    """Request body used to update the heartbeat timestamp for a session."""

    timestamp: datetime | None = None


router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/commands", response_model=Session, status_code=status.HTTP_201_CREATED)
async def execute_create_command(
    payload: SessionCreateCommand,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    runner_client: Annotated[RunnerCommandClient, Depends(get_runner_command_client)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Issue ``POST /sessions`` against a runner and persist the response."""

    runner = None
    if payload.runner_id is not None:
        runner = await runners.get(payload.runner_id)
        if runner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Runner not found",
            )
    else:
        runner = await runners.select_next(requires_vnc=not payload.headless)
        if runner is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No healthy runners available",
            )

    assert runner is not None  # Narrow type after selection.

    try:
        session = await runner_client.create_session(runner, payload)
    except RunnerCommandError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    enriched = _enrich_session(session, runner, token_service, user)
    await registry.upsert(enriched)
    await _publish_session_event(bridge, enriched, SessionEventType.CREATED)
    return enriched


@router.patch("/commands/{session_id}", response_model=Session)
async def execute_update_command(
    session_id: UUID,
    payload: SessionUpdateCommand,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    runner_client: Annotated[RunnerCommandClient, Depends(get_runner_command_client)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Proxy ``PATCH /sessions`` to the runner and mirror the outcome locally."""

    try:
        current = await registry.get(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc

    runner = await runners.get(current.runner_id)
    if runner is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runner unavailable",
        )

    try:
        session = await runner_client.update_session(runner, session_id, payload)
    except RunnerCommandError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    enriched = _enrich_session(session, runner, token_service, user)
    await registry.upsert(enriched)
    event_type = (
        SessionEventType.ENDED
        if enriched.status is SessionStatus.DEAD
        else SessionEventType.UPDATED
    )
    await _publish_session_event(bridge, enriched, event_type)
    return enriched


@router.delete("/commands/{session_id}", response_model=Session)
async def execute_delete_command(
    session_id: UUID,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    runner_client: Annotated[RunnerCommandClient, Depends(get_runner_command_client)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Proxy ``DELETE /sessions`` to the runner and drop the local record."""

    try:
        current = await registry.get(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc

    runner = await runners.get(current.runner_id)
    if runner is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runner unavailable",
        )

    try:
        session = await runner_client.delete_session(runner, session_id)
    except RunnerCommandError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    enriched = _enrich_session(session, runner, token_service, user)
    await registry.delete(session_id)
    event_type = (
        SessionEventType.ENDED
        if enriched.status is SessionStatus.DEAD
        else SessionEventType.UPDATED
    )
    await _publish_session_event(bridge, enriched, event_type)
    return enriched


@router.get("", response_model=list[Session])
async def list_sessions(
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[Session]:
    """Return all sessions currently tracked by the gateway."""

    sessions = await registry.list()
    return await _enrich_registry_sessions(sessions, runners, token_service, user)


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    session: Session,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Register a new session emitted by a runner."""

    runner = await runners.get(session.runner_id)
    enriched = _enrich_session(session, runner, token_service, user)
    try:
        stored = await registry.add(enriched)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await _publish_session_event(bridge, stored, SessionEventType.CREATED)
    return stored


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: UUID,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Return a single session by identifier."""

    try:
        stored = await registry.get(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc

    enriched = await _enrich_registry_sessions([stored], runners, token_service, user)
    return enriched[0]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Response:
    """Delete a session from the registry."""

    try:
        session = await registry.get(session_id)
        await registry.delete(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    event_session = (
        session
        if session.status is SessionStatus.DEAD
        else session.model_copy(
            update={
                "status": SessionStatus.DEAD,
                "ended_at": datetime.now(tz=UTC),
            }
        )
    )
    await _publish_session_event(bridge, event_session, SessionEventType.ENDED)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/proxy", response_model=Session)
async def update_proxy(
    session_id: UUID,
    payload: SessionProxySettings,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Update proxy configuration for a session."""

    try:
        session = await registry.update_proxy(session_id, payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    enriched = await _enrich_registry_sessions([session], runners, token_service, user)
    result = enriched[0]
    await _publish_session_event(bridge, result, SessionEventType.UPDATED)
    return result


@router.post("/{session_id}/touch", response_model=Session)
async def touch_session(
    session_id: UUID,
    payload: TouchPayload,
    registry: Annotated[SessionRegistry, Depends(get_session_registry)],
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    runners: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    token_service: Annotated[VncTokenService, Depends(get_vnc_token_service)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Session:
    """Update the ``last_seen_at`` timestamp for a session."""

    try:
        session = await registry.touch(session_id, timestamp=payload.timestamp)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    enriched = await _enrich_registry_sessions([session], runners, token_service, user)
    result = enriched[0]
    await _publish_session_event(bridge, result, SessionEventType.UPDATED)
    return result


async def _enrich_registry_sessions(
    sessions: Iterable[Session],
    runners: RunnerRegistry,
    token_service: VncTokenService,
    user: AuthenticatedUser,
) -> list[Session]:
    """Return sessions enriched with the latest runner overrides and tokens.

    Args:
        sessions: Iterable of session snapshots obtained from the registry.
        runners: Source of runner metadata used for VNC override templates.
        token_service: Issuer responsible for minting short-lived VNC tokens.
        user: Authenticated subject receiving the session payload.

    Returns:
        list[Session]: Sessions updated with the most recent VNC URLs and
        gateway-minted access tokens when necessary.

    Example:
        >>> await _enrich_registry_sessions([session], runners, token_service, user)  # doctest: +SKIP
    """

    snapshots = list(sessions)
    if not snapshots:
        return []

    runner_cache: dict[str, Runner | None] = {}
    enriched: list[Session] = []
    for snapshot in snapshots:
        runner: Runner | None = None
        runner_id = snapshot.runner_id
        if runner_id:
            if runner_id in runner_cache:
                runner = runner_cache[runner_id]
            else:
                runner = await runners.get(runner_id)
                runner_cache[runner_id] = runner
        enriched.append(_enrich_session(snapshot, runner, token_service, user))
    return enriched


async def _publish_session_event(
    bridge: AbstractSessionEventBridge,
    session: Session,
    event_type: SessionEventType,
) -> None:
    """Helper that constructs and emits a :class:`SessionEvent` to the bridge.

    Args:
        bridge: Event broadcaster shared by SSE and WebSocket transports.
        session: Session snapshot to include in the event payload.
        event_type: Semantic classification of the change being announced.

    Returns:
        None. The coroutine publishes the event and completes once subscribers
        have been notified.

    Example:
        >>> await _publish_session_event(bridge, session, SessionEventType.UPDATED)  # doctest: +SKIP
    """

    event = SessionEvent(
        session=session,
        occurred_at=datetime.now(tz=UTC),
        type=event_type,
    )
    await bridge.publish(event)


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
