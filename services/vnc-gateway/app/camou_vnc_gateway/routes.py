"""HTTP and WebSocket routes exposed by the VNC gateway."""

from __future__ import annotations

import logging
from typing import Annotated, Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from starlette import status

from .dependencies import get_connection_registry, get_runner_proxy, get_token_validator
from .metrics import (
    ConnectionRegistry,
    MetricsRenderNotSupportedError,
    record_token_validation_failure,
    render_prometheus_metrics,
)
from .proxy import RunnerProxy, TargetPortError
from .token import TokenValidationError, TokenValidator

LOG = logging.getLogger(__name__)


router = APIRouter()


def _extract_token(request: Request) -> str:
    """Return the VNC token supplied with an HTTP request.

    Args:
        request (Request): Incoming FastAPI request expected to carry the token
            through either the ``X-VNC-Token`` header or the ``token``/
            ``access_token`` query parameters.

    Returns:
        str: The resolved VNC token ready for validation.

    Raises:
        HTTPException: If no token is present in either the headers or query
            parameters.

    Example:
        >>> scope = {"type": "http", "headers": [], "query_string": b"token=abc"}
        >>> request = Request(scope)  # doctest: +SKIP
        >>> _extract_token(request)  # doctest: +SKIP
        'abc'

    The gateway attaches tokens via the ``X-VNC-Token`` header during regular
    operation, but we fall back to the query string so pre-signed iframe URLs
    keep working for consumers that cannot set custom headers.
    """

    token = _coalesce_token(
        request.headers.get("X-VNC-Token"),
        request.query_params,
    )
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing VNC access token")
    return token


def _coalesce_token(header_value: str | None, query_params: Mapping[str, str]) -> str | None:
    """Return the first available token from headers or query parameters.

    Args:
        header_value (str | None): Token provided via request headers.
        query_params (Mapping[str, str]): Parsed query parameters from the
            request/connection.

    Returns:
        str | None: The token when present, otherwise ``None`` so callers can
        decide how to handle missing credentials.

    Example:
        >>> _coalesce_token(None, {"token": "abc"})
        'abc'
    """

    token = header_value
    if token:
        return token
    token = query_params.get("token")
    if token:
        return token
    return query_params.get("access_token")


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
        record_token_validation_failure(reason=str(exc))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    async with registry.track(session_id=session_id, channel="http"):
        try:
            return await proxy.forward_http(session_id=session_id, request=request)
        except TargetPortError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.websocket("/sessions/{session_id}/ws")
async def proxy_session_ws(
    websocket: WebSocket,
    session_id: str,
    validator: ValidatorDep,
    proxy: RunnerProxyDep,
    registry: RegistryDep,
):
    """Validate the WebSocket upgrade request and relay traffic."""

    token = _coalesce_token(
        websocket.headers.get("x-vnc-token") or websocket.headers.get("X-VNC-Token"),
        websocket.query_params,
    )
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        validator.validate(session_id, token)
    except TokenValidationError as exc:
        LOG.warning("WebSocket token validation failed", extra={"session_id": session_id})
        record_token_validation_failure(reason=str(exc))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
        return

    async with registry.track(session_id=session_id, channel="ws"):
        await proxy.forward_websocket(session_id=session_id, websocket=websocket)


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics collected by the service."""

    try:
        payload, content_type = render_prometheus_metrics()
    except MetricsRenderNotSupportedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(content=payload, media_type=content_type)


__all__ = ["router"]
