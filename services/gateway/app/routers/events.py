"""Realtime event streaming endpoints."""

from __future__ import annotations

from typing import Annotated

from core import AbstractSessionEventBridge, SessionEvent
from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from ..deps import get_event_bridge
from ..deps.security import authenticate_websocket, get_authenticator, get_current_user
from ..security import AuthenticatedUser, KeycloakAuthenticator

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def publish_session_event(
    event: SessionEvent,
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    _user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> Response:
    """Accept a :class:`SessionEvent` from a runner and fan it out to clients.

    Args:
        event: Payload describing the session transition that occurred on the
            runner.
        bridge: Application-scoped event bridge that relays events to SSE and
            WebSocket subscribers.
        _user: Authenticated principal publishing the event. The value is not
            used directly but ensures that callers are authorised via
            :func:`get_current_user` before an event enters the system.

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
