"""Security-related FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..security import AuthenticatedUser, AuthenticationError, KeycloakAuthenticator

_bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticator(request: Request) -> KeycloakAuthenticator:
    """Return the authenticator stored on the FastAPI application instance."""

    return request.app.state.authenticator  # type: ignore[attr-defined]


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    authenticator: Annotated[
        KeycloakAuthenticator, Depends(get_authenticator)
    ],
) -> AuthenticatedUser:
    """Validate the incoming bearer token and return the authenticated user.

    The SSE endpoint relies on the browser-native ``EventSource`` implementation
    which does not allow specifying custom headers. To keep that endpoint
    functional we also honour the ``access_token`` (or ``token`` for parity with
    the WebSocket endpoint) query parameter whenever the ``Authorization``
    header is absent.
    """

    token: str | None
    if credentials is not None:
        token = credentials.credentials
    else:
        # ``token`` mirrors the WebSocket query parameter for consistency.
        token = request.query_params.get("access_token") or request.query_params.get("token")

    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
    try:
        return await authenticator.authenticate(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


async def authenticate_websocket(
    websocket: WebSocket,
    authenticator: KeycloakAuthenticator,
) -> AuthenticatedUser:
    """Perform bearer token authentication for WebSocket connections."""

    authorization = websocket.headers.get("Authorization")
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    else:
        token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise AuthenticationError("Missing bearer token for WebSocket connection")
    try:
        return await authenticator.authenticate(token)
    except AuthenticationError as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise exc
