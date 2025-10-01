"""Realtime event streaming endpoints."""

from __future__ import annotations

from typing import Annotated

from core import AbstractSessionEventBridge
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..deps import get_event_bridge
from ..deps.security import authenticate_websocket, get_authenticator, get_current_user
from ..security import AuthenticatedUser, KeycloakAuthenticator

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_class=StreamingResponse)
async def stream_events(
    bridge: Annotated[AbstractSessionEventBridge, Depends(get_event_bridge)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> StreamingResponse:
    """Provide a Server-Sent Events stream for session events.

    Clients may authenticate with a bearer token supplied either via the
    ``Authorization`` header or the ``access_token`` query parameter to mirror
    WebSocket semantics.
    """

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
