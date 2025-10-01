"""Security-related FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..security import AuthenticatedUser, AuthenticationError, KeycloakAuthenticator

_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_bearer_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Return a bearer token from headers or ``access_token`` query parameter.

    Args:
        request: Incoming HTTP request used to access query parameters.
        credentials: Parsed ``Authorization`` header produced by ``HTTPBearer``.

    Returns:
        Optional token string if found either in the ``Authorization`` header or
        the ``access_token`` query parameter.

    Example:
        >>> scope = {"type": "http", "query_string": b"access_token=abc"}
        >>> request = Request(scope)
        >>> _extract_bearer_token(request, None)
        'abc'
    """

    if credentials is not None:
        return credentials.credentials

    token = request.query_params.get("access_token")
    if token:
        return token
    return None


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
    """Validate a bearer token delivered via headers or query parameters.

    The HTTP SSE endpoint accepts tokens through the ``access_token`` query
    parameter to mirror the WebSocket implementation.  This helper inspects
    both the ``Authorization`` header and query string before delegating to the
    authenticator.
    """

    token = _extract_bearer_token(request, credentials)
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
