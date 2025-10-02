"""Security-related FastAPI dependencies."""

from __future__ import annotations

import ipaddress
import logging
from typing import Annotated, Iterable, Mapping

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import GatewaySettings
from ..security import AuthenticatedUser, AuthenticationError, KeycloakAuthenticator

_bearer_scheme = HTTPBearer(auto_error=False)
_LOGGER = logging.getLogger("gateway.security")


def get_authenticator(request: Request) -> KeycloakAuthenticator:
    """Return the authenticator stored on the FastAPI application instance.

    Args:
        request: Incoming request whose ``app.state`` contains the authenticator
            singleton initialised during application startup.

    Returns:
        KeycloakAuthenticator: Authenticator used to validate bearer tokens.

    Example:
        >>> authenticator = get_authenticator(request)
        >>> await authenticator.authenticate("token")
    """

    return request.app.state.authenticator  # type: ignore[attr-defined]


def get_gateway_settings(request: Request) -> GatewaySettings:
    """Return the gateway configuration attached to the FastAPI application.

    Args:
        request: Incoming request object with ``app.state.settings`` populated by
            :func:`app.main.create_app`.

    Returns:
        GatewaySettings: Immutable snapshot of the runtime configuration.

    Example:
        >>> settings = get_gateway_settings(request)
        >>> settings.jwt_jwks_url
        'https://idp.local/jwks'
    """

    return request.app.state.settings  # type: ignore[attr-defined]


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ],
    authenticator: Annotated[
        KeycloakAuthenticator, Depends(get_authenticator)
    ],
    settings: Annotated[GatewaySettings, Depends(get_gateway_settings)],
) -> AuthenticatedUser:
    """Authenticate HTTP/SSE callers using trusted networks or bearer tokens.

    The dependency honours ``access_token``/``token`` query parameters to stay
    compatible with browser-native ``EventSource`` clients that cannot set custom
    headers.

    Args:
        request: FastAPI request object describing the inbound call.
        credentials: Optional bearer credentials extracted from the
            ``Authorization`` header by :class:`HTTPBearer`.
        authenticator: Keycloak authenticator used when bearer validation is
            required.
        settings: Gateway settings providing trusted networks and headers.

    Returns:
        AuthenticatedUser: Either a synthetic internal user (for trusted
        networks) or the principal decoded from the bearer token.

    Raises:
        HTTPException: If credentials are missing or invalid for external
            callers.

    Example:
        >>> request = Request(scope)
        >>> user = await get_current_user(request, None, authenticator, settings)
        >>> user.subject
        'internal:10.0.0.1'
    """

    trusted_source = _resolve_trusted_source(
        client_host=request.client.host if request.client else None,
        header_value=_extract_trusted_header(request.headers, settings.trusted_header),
        networks=settings.trusted_cidrs,
    )
    if trusted_source is not None:
        user = AuthenticatedUser(subject=f"internal:{trusted_source}")
        _LOGGER.info(
            "authenticated",
            extra={
                "auth_strategy": "internal-bypass",
                "transport": "http",
                "source_ip": trusted_source,
                "sub": user.subject,
            },
        )
        return user

    token: str | None
    if credentials is not None:
        token = credentials.credentials
    else:
        # ``token`` mirrors the WebSocket query parameter for consistency.
        token = request.query_params.get("access_token") or request.query_params.get("token")

    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")
    try:
        user = await authenticator.authenticate(token)
        _LOGGER.info(
            "authenticated",
            extra={
                "auth_strategy": "bearer",
                "transport": "http",
                "sub": user.subject,
                "email": user.email,
            },
        )
        return user
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


async def authenticate_websocket(
    websocket: WebSocket,
    authenticator: KeycloakAuthenticator,
) -> AuthenticatedUser:
    """Authenticate WebSocket connections via trusted networks or bearer tokens.

    Args:
        websocket: WebSocket connection to inspect for credentials.
        authenticator: Keycloak authenticator enforcing bearer tokens for
            external callers.

    Returns:
        AuthenticatedUser: Either the synthetic trusted-network user or the
        bearer-authenticated principal.

    Raises:
        AuthenticationError: If authentication fails and the connection must be
            rejected.

    Example:
        >>> user = await authenticate_websocket(websocket, authenticator)
        >>> user.subject
        'internal:10.0.0.1'
    """

    settings: GatewaySettings = websocket.app.state.settings  # type: ignore[attr-defined]
    trusted_source = _resolve_trusted_source(
        client_host=websocket.client.host if websocket.client else None,
        header_value=_extract_trusted_header(websocket.headers, settings.trusted_header),
        networks=settings.trusted_cidrs,
    )
    if trusted_source is not None:
        user = AuthenticatedUser(subject=f"internal:{trusted_source}")
        _LOGGER.info(
            "authenticated",
            extra={
                "auth_strategy": "internal-bypass",
                "transport": "websocket",
                "source_ip": trusted_source,
                "sub": user.subject,
            },
        )
        return user

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
        user = await authenticator.authenticate(token)
        _LOGGER.info(
            "authenticated",
            extra={
                "auth_strategy": "bearer",
                "transport": "websocket",
                "sub": user.subject,
                "email": user.email,
            },
        )
        return user
    except AuthenticationError as exc:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise exc


def _resolve_trusted_source(
    *,
    client_host: str | None,
    header_value: str | None,
    networks: Iterable[ipaddress._BaseNetwork],
) -> str | None:
    """Return the trusted source IP when it falls within configured networks.

    Args:
        client_host: Peer IP reported by the TCP connection.
        header_value: Optional value of the configured trusted header.
        networks: Iterable of CIDR ranges considered internal.

    Returns:
        str | None: The first IP string that belongs to the trusted networks,
        prioritising header values before the socket address.

    Example:
        >>> _resolve_trusted_source(
        ...     client_host="203.0.113.10",
        ...     header_value="10.0.0.1, 192.0.2.1",
        ...     networks=[ipaddress.ip_network("10.0.0.0/8")],
        ... )
        '10.0.0.1'
    """

    if not networks:
        return None
    candidates: list[tuple[str, ipaddress._BaseAddress]] = []
    if header_value:
        parts = [part.strip() for part in header_value.split(",")]
        for part in parts:
            if not part:
                continue
            address = _parse_ip(part)
            if address is not None:
                candidates.append((part, address))
    if client_host:
        address = _parse_ip(client_host)
        if address is not None:
            candidates.append((client_host, address))
    for original, address in candidates:
        if any(address in network for network in networks):
            return original
    return None


def _extract_trusted_header(headers: Mapping[str, str], header_name: str | None) -> str | None:
    """Return the configured trusted header value if present.

    Args:
        headers: Mapping of HTTP headers exposed by FastAPI/Starlette.
        header_name: Configured header name or :data:`None` when disabled.

    Returns:
        str | None: Header value if available.

    Example:
        >>> _extract_trusted_header({"x-real-ip": "10.0.0.1"}, "x-real-ip")
        '10.0.0.1'
    """

    if not header_name:
        return None
    return headers.get(header_name)


def _parse_ip(raw: str) -> ipaddress._BaseAddress | None:
    """Parse a string into an IP address, returning ``None`` when invalid.

    Args:
        raw: String representation of an IPv4 or IPv6 address.

    Returns:
        ipaddress._BaseAddress | None: Parsed address or :data:`None` when
        parsing fails.

    Example:
        >>> _parse_ip('10.0.0.1')
        IPv4Address('10.0.0.1')
    """

    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None
