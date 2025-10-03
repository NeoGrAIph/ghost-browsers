"""Unit tests for gateway authentication helpers."""

from __future__ import annotations

import ipaddress
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, status
from starlette.datastructures import Headers, QueryParams

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.config import GatewaySettings  # noqa: E402
from app.deps.security import authenticate_websocket, get_current_user  # noqa: E402
from app.security import (  # noqa: E402
    AuthenticatedUser,
    AuthenticationError,
    VncTokenService,
)


class DummyAuthenticator:
    """Minimal authenticator stub used to track authentication attempts."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate(self, token: str) -> AuthenticatedUser:
        """Record the token and return a synthetic authenticated user."""

        self.tokens.append(token)
        return AuthenticatedUser(subject="token-user")


class DummyWebSocket:
    """Lightweight mock for :class:`fastapi.WebSocket` used in unit tests."""

    def __init__(
        self,
        *,
        host: str,
        headers: list[tuple[bytes, bytes]] | None = None,
        query_string: str = "",
        settings: GatewaySettings,
    ) -> None:
        self.headers = Headers(raw=headers or [])
        self.query_params = QueryParams(query_string)
        self.client = SimpleNamespace(host=host, port=443)
        self.app = SimpleNamespace(state=SimpleNamespace(settings=settings))
        self._closed: list[int] = []

    async def close(self, code: int) -> None:
        """Record the close code for later assertions."""

        self._closed.append(code)

    @property
    def closed_codes(self) -> list[int]:
        """Return the list of WebSocket close codes captured during the test."""

        return self._closed


def _build_request(
    *,
    client_host: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> Request:
    """Create a Starlette :class:`Request` object for dependency testing."""

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": (client_host, 443),
        "headers": headers or [],
        "query_string": query_string,
    }
    return Request(scope)


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO-powered tests to execute on the asyncio backend."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_http_trusted_client_bypasses_token_validation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Requests originating from trusted networks skip bearer authentication."""

    settings = GatewaySettings(
        trusted_cidrs=[ipaddress.ip_network("10.0.0.0/8")],
    )
    request = _build_request(client_host="10.1.2.3")
    authenticator = DummyAuthenticator()

    caplog.set_level(logging.INFO, logger="gateway.security")
    user = await get_current_user(
        request=request,
        credentials=None,
        authenticator=authenticator,
        settings=settings,
    )

    assert user.subject == "internal:10.1.2.3"
    assert authenticator.tokens == []
    assert any(
        record.__dict__.get("auth_strategy") == "internal-bypass"
        for record in caplog.records
    )


@pytest.mark.anyio("asyncio")
async def test_http_trusted_header_is_honoured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The configured trusted header overrides the socket peer address."""

    settings = GatewaySettings(
        trusted_cidrs=[ipaddress.ip_network("10.0.0.0/8")],
        trusted_header="X-Real-IP",
    )
    request = _build_request(
        client_host="203.0.113.10",
        headers=[(b"x-real-ip", b"10.3.4.5, 192.0.2.1")],
    )
    authenticator = DummyAuthenticator()

    caplog.set_level(logging.INFO, logger="gateway.security")
    user = await get_current_user(
        request=request,
        credentials=None,
        authenticator=authenticator,
        settings=settings,
    )

    assert user.subject == "internal:10.3.4.5"
    assert authenticator.tokens == []
    assert any(
        record.__dict__.get("source_ip") == "10.3.4.5"
        for record in caplog.records
    )


@pytest.mark.anyio("asyncio")
async def test_http_invalid_trusted_header_falls_back_to_bearer() -> None:
    """Invalid header values must not trigger the internal bypass."""

    settings = GatewaySettings(
        trusted_cidrs=[ipaddress.ip_network("10.0.0.0/8")],
        trusted_header="X-Real-IP",
    )
    request = _build_request(
        client_host="203.0.113.10",
        headers=[(b"x-real-ip", b"not-an-ip")],
    )
    authenticator = DummyAuthenticator()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            request=request,
            credentials=None,
            authenticator=authenticator,
            settings=settings,
        )

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert authenticator.tokens == []


@pytest.mark.anyio("asyncio")
async def test_websocket_trusted_client_bypasses_token_validation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """WebSocket connections from trusted networks skip bearer authentication."""

    settings = GatewaySettings(
        trusted_cidrs=[ipaddress.ip_network("10.0.0.0/8")],
    )
    websocket = DummyWebSocket(host="10.9.0.1", settings=settings)
    authenticator = DummyAuthenticator()

    caplog.set_level(logging.INFO, logger="gateway.security")
    user = await authenticate_websocket(websocket=websocket, authenticator=authenticator)

    assert user.subject == "internal:10.9.0.1"
    assert authenticator.tokens == []
    assert websocket.closed_codes == []
    assert any(
        record.__dict__.get("transport") == "websocket"
        for record in caplog.records
    )


@pytest.mark.anyio("asyncio")
async def test_websocket_external_client_without_token_is_rejected() -> None:
    """External WebSocket callers must supply a bearer token."""

    settings = GatewaySettings(
        trusted_cidrs=[ipaddress.ip_network("10.0.0.0/8")],
    )
    websocket = DummyWebSocket(host="203.0.113.10", settings=settings)
    authenticator = DummyAuthenticator()

    with pytest.raises(AuthenticationError):
        await authenticate_websocket(websocket=websocket, authenticator=authenticator)

    assert websocket.closed_codes == [status.WS_1008_POLICY_VIOLATION]
    assert authenticator.tokens == []


@pytest.mark.parametrize("ttl", [0, -90])
def test_vnc_token_service_rejects_non_positive_ttl(ttl: int) -> None:
    """`VncTokenService` refuses to operate with zero/negative TTL values."""

    with pytest.raises(ValueError) as excinfo:
        VncTokenService(secret="secret", ttl_seconds=ttl)

    assert "between 1 and 300 seconds" in str(excinfo.value)
