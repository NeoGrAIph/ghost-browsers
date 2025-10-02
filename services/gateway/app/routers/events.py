"""Realtime HTTP and WebSocket endpoints for session and workstation events."""

from __future__ import annotations

from typing import Annotated

from core import (
    AbstractSessionEventBridge,
    AbstractWorkstationEventBridge,
    SessionEvent,
    WorkstationEvent,
)
from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from ..deps import (
    get_event_bridge,
    get_workstation_event_bridge,
    get_workstation_event_bridge_ws,
)
from ..deps.security import authenticate_websocket, get_authenticator, get_current_user
from ..security import AuthenticatedUser, KeycloakAuthenticator

router = APIRouter(prefix="/events", tags=["events"])
workstation_router = APIRouter(prefix="/workstations/events", tags=["workstations"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def publish_session_event(
    event: SessionEvent,
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
) -> Response:
    """Accept a :class:`SessionEvent` from a runner and fan it out to clients.

    Args:
        event: Payload describing the session transition that occurred on the
            runner.
        bridge: Application-scoped event bridge that relays events to SSE and
            WebSocket subscribers.

    Returns:
        Response: ``202 Accepted`` response confirming that the event was
        enqueued for broadcasting.

    Example:
        >>> await publish_session_event(event, bridge)  # doctest: +SKIP
    """

    await bridge.publish(event)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("", response_class=StreamingResponse)
async def stream_events(
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> StreamingResponse:
    """Provide a Server-Sent Events stream for session events."""

    async def iterator() -> str:
        subscription = await bridge.subscribe(replay_latest=True)
        try:
            async for event in subscription:
                yield f"data: {event.model_dump_json(by_alias=True)}\n\n"
        finally:
            await subscription.aclose()

    return StreamingResponse(iterator(), media_type="text/event-stream")


@router.websocket("/ws")
async def websocket_events(
    websocket: WebSocket,
    authenticator: Annotated[KeycloakAuthenticator, Depends(get_authenticator)],
) -> None:
    """Relay session events over a WebSocket connection."""

    await authenticate_websocket(websocket, authenticator)
    await websocket.accept()
    bridge: AbstractSessionEventBridge = websocket.app.state.event_bridge  # type: ignore[attr-defined]
    subscription = await bridge.subscribe(replay_latest=True)
    try:
        async for event in subscription:
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:  # pragma: no cover - handshake drop
        pass
    finally:
        await subscription.aclose()


@workstation_router.post("", status_code=status.HTTP_202_ACCEPTED)
async def publish_workstation_event(
    event: WorkstationEvent,
    bridge: Annotated[AbstractWorkstationEventBridge, Depends(get_workstation_event_bridge)],
) -> Response:
    """Accept a :class:`WorkstationEvent` and broadcast it downstream."""

    await bridge.publish(event)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@workstation_router.get("", response_class=StreamingResponse)
async def stream_workstation_events(
    bridge: Annotated[AbstractWorkstationEventBridge, Depends(get_workstation_event_bridge)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> StreamingResponse:
    """Provide a Server-Sent Events stream for workstation events."""

    del user

    async def iterator() -> str:
        subscription = await bridge.subscribe(replay_latest=True)
        try:
            async for event in subscription:
                payload = event.model_dump_json(by_alias=True)
                yield f"data: {payload}\n\n"
        finally:
            await subscription.aclose()

    return StreamingResponse(iterator(), media_type="text/event-stream")


@workstation_router.websocket("/ws")
async def websocket_workstation_events(
    websocket: WebSocket,
    authenticator: Annotated[KeycloakAuthenticator, Depends(get_authenticator)],
    bridge: Annotated[
        AbstractWorkstationEventBridge, Depends(get_workstation_event_bridge_ws)
    ],
) -> None:
    """Relay workstation events over a WebSocket connection."""

    await authenticate_websocket(websocket, authenticator)
    await websocket.accept()
    subscription = await bridge.subscribe(replay_latest=True)
    try:
        async for event in subscription:
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:  # pragma: no cover - handshake drop
        pass
    finally:
        await subscription.aclose()
