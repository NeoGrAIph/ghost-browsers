"""HTTP and WebSocket routes exposed by the VNC gateway."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from starlette import status

from .dependencies import get_connection_registry, get_runner_proxy, get_token_validator
from .metrics import ConnectionRegistry
from .proxy import RunnerProxy
from .token import TokenValidationError, TokenValidator

LOG = logging.getLogger(__name__)


router = APIRouter()


def _extract_token(request: Request) -> str:
    """Extract VNC token from the ``X-VNC-Token`` header.

    The header based approach keeps the implementation close to the expected
    production flow where the public Gateway injects tokens for downstream
    services without exposing them to query parameters which might leak through
    logs.
    """

    token = request.headers.get("X-VNC-Token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing X-VNC-Token header")
    return token


ValidatorDep = Annotated[TokenValidator, Depends(get_token_validator)]
RunnerProxyDep = Annotated[RunnerProxy, Depends(get_runner_proxy)]
RegistryDep = Annotated[ConnectionRegistry, Depends(get_connection_registry)]


@router.get("/sessions/{session_id}")
async def proxy_session(
    session_id: str,
    request: Request,
    validator: ValidatorDep,
    proxy: RunnerProxyDep,
    registry: RegistryDep,
):
    """Validate the token and forward the HTTP request to Runner."""

    token = _extract_token(request)
    try:
        validator.validate(session_id, token)
    except TokenValidationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    async with registry.track(session_id=session_id, channel="http"):
        return await proxy.forward_http(session_id=session_id, request=request)


@router.websocket("/sessions/{session_id}/ws")
async def proxy_session_ws(
    websocket: WebSocket,
    session_id: str,
    validator: ValidatorDep,
    proxy: RunnerProxyDep,
    registry: RegistryDep,
):
    """Validate the WebSocket upgrade request and relay traffic."""

    token = websocket.headers.get("x-vnc-token") or websocket.headers.get("X-VNC-Token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        validator.validate(session_id, token)
    except TokenValidationError as exc:
        LOG.warning("WebSocket token validation failed", extra={"session_id": session_id})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
        return

    async with registry.track(session_id=session_id, channel="ws"):
        await proxy.forward_websocket(session_id=session_id, websocket=websocket)


__all__ = ["router"]
