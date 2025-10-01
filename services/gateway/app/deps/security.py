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
    """Return the authenticator registered on the FastAPI application instance.

    Args:
        request: Incoming FastAPI request exposing the shared ``state`` object.

    Returns:
        The :class:`~app.security.KeycloakAuthenticator` configured during
        application startup.

    Raises:
        AttributeError: If the application ``state`` does not carry an
            ``authenticator`` attribute.  The gateway initialiser always sets
            the attribute, therefore an error here signals a misconfigured test
            harness.

    Example:
        A FastAPI dependency can reuse this helper to access the shared
        authenticator::

            @router.get("/sessions")
            async def list_sessions(
                authenticator: KeycloakAuthenticator = Depends(get_authenticator),
            ) -> list[dict[str, object]]:
                ...
    """

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

    Args:
        request: Incoming HTTP request that may transport the token either via
            headers or the ``access_token`` query string parameter.
        credentials: Parsed bearer credentials produced by
            :class:`fastapi.security.HTTPBearer`.  The dependency returns
            ``None`` when the ``Authorization`` header is absent, allowing us to
            inspect query parameters instead.
        authenticator: Component responsible for verifying and decoding the
            access token into an :class:`~app.security.AuthenticatedUser`.

    Returns:
        The authenticated user represented by the supplied bearer token.

    Raises:
        HTTPException: If the token is missing or rejected by the authenticator
            implementation.

    Example:
        >>> scope = {"type": "http", "query_string": b"access_token=test", "headers": []}
        >>> request = Request(scope)
        >>> class DummyAuthenticator:
        ...     async def authenticate(self, token: str) -> AuthenticatedUser:
        ...         assert token == "test"
        ...         return AuthenticatedUser(subject="demo", email=None)
        >>> import anyio
        >>> anyio.run(get_current_user, request, None, DummyAuthenticator())
        AuthenticatedUser(subject='demo', email=None)
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
    """Perform bearer token authentication for WebSocket connections.

    Args:
        websocket: Active WebSocket connection requiring authentication.
        authenticator: Component capable of validating bearer tokens.

    Returns:
        The :class:`~app.security.AuthenticatedUser` associated with the
        provided token.

    Raises:
        AuthenticationError: If the token cannot be located or fails
            validation.  The helper closes the WebSocket using code ``1008``
            before propagating the error to the caller.

    Example:
        Within a FastAPI WebSocket route the helper is invoked before accepting
        the connection::

            @app.websocket("/events/ws")
            async def session_events(endpoint: WebSocket) -> None:
                user = await authenticate_websocket(endpoint, authenticator)
                await endpoint.accept()
                ...
    """

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
