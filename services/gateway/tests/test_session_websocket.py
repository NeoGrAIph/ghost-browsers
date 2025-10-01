"""Integration tests for the session WebSocket proxy endpoint."""

from __future__ import annotations

import asyncio
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import websockets
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status
from starlette.websockets import WebSocketDisconnect

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app import create_app  # noqa: E402
from app.config import GatewaySettings  # noqa: E402
from app.deps import get_vnc_token_service  # noqa: E402
from app.deps.security import get_authenticator, get_current_user  # noqa: E402
from app.security import AuthenticatedUser, VncTokenService  # noqa: E402
from core import Runner, SessionStatus  # noqa: E402


@pytest.fixture()
def gateway_app() -> FastAPI:
    """Return a FastAPI application configured for WebSocket proxy tests.

    Example:
        >>> app = gateway_app()  # doctest: +SKIP
        >>> isinstance(app, FastAPI)
        True
    """

    settings = GatewaySettings(
        discovery_mode="static",
        runners=[
            Runner(
                id="runner-1",
                base_url="http://runner-1",
                total_slots=1,
                supports_vnc=True,
                vnc_http_url_template="https://vnc.example/view/{id}",
                vnc_ws_url_template="wss://vnc.example/ws/{id}",
            )
        ],
        jwt_jwks_url="http://jwks.local",
        vnc_token_ttl_seconds=120,
        vnc_token_secret="unit-test-secret",
    )
    app = create_app(settings)

    user = AuthenticatedUser(subject="tester", email="tester@example.com")

    async def _user_override() -> AuthenticatedUser:
        return user

    token_service = VncTokenService(
        secret="unit-test-secret",
        ttl_seconds=settings.vnc_token_ttl_seconds,
    )

    class _DummyAuthenticator:
        async def authenticate(self, token: str) -> AuthenticatedUser:
            """Return the static authenticated user for tests."""

            return user

    dummy_auth = _DummyAuthenticator()

    app.state.vnc_tokens = token_service
    app.state.authenticator = dummy_auth
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_authenticator] = lambda: dummy_auth
    app.dependency_overrides[get_vnc_token_service] = lambda: token_service
    app.state.runner_ws_proxy.connect_timeout = 30.0

    return app


@pytest.fixture()
def gateway_client(gateway_app: FastAPI) -> TestClient:
    """Return a FastAPI test client with WebSocket support enabled.

    Example:
        >>> client = gateway_client(gateway_app)  # doctest: +SKIP
        >>> isinstance(client, TestClient)
        True
    """

    client = TestClient(gateway_app)
    yield client
    client.close()


@pytest.fixture()
def websocket_echo_server(free_tcp_port: int) -> str:
    """Start an in-memory echo server and return its WebSocket URL.

    Example:
        >>> url = websocket_echo_server(8765)  # doctest: +SKIP
        >>> url.startswith("ws://127.0.0.1")
        True
    """

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    server_holder: dict[str, websockets.server.Serve] = {}

    async def main() -> None:
        async def handler(connection: websockets.WebSocketServerProtocol) -> None:
            async for payload in connection:
                await connection.send(payload)

        server = await websockets.serve(handler, "127.0.0.1", free_tcp_port)
        server_holder["server"] = server
        ready.set()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait()
    try:
        yield f"ws://127.0.0.1:{free_tcp_port}/ws"
    finally:
        async def shutdown() -> None:
            server = server_holder.get("server")
            if server is not None:
                server.close()
                await server.wait_closed()

        future = asyncio.run_coroutine_threadsafe(shutdown(), loop)
        try:
            future.result(timeout=5)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO to use asyncio to avoid optional trio dependency.

    Example:
        >>> anyio_backend()
        'asyncio'
    """

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_session_websocket_proxy_roundtrip(
    gateway_app: FastAPI,
    gateway_client: TestClient,
    websocket_echo_server: str,
) -> None:
    """The proxy should relay text and binary frames bidirectionally."""

    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "ws_endpoint": websocket_echo_server,
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    assert response.json()["ws_endpoint"] == f"/sessions/{session_id}/ws"

    resolved = await gateway_app.state.runner_registry.resolve_session_ws_target(UUID(session_id))
    assert resolved == websocket_echo_server

    with gateway_client.websocket_connect(
        f"/sessions/{session_id}/ws?token=dummy"
    ) as client_ws:
        client_ws.send_text("ping")
        assert client_ws.receive_text() == "ping"
        client_ws.send_bytes(b"binary")
        assert client_ws.receive_bytes() == b"binary"


@pytest.mark.anyio("asyncio")
async def test_session_websocket_proxy_upstream_failure(
    gateway_app: FastAPI,
    gateway_client: TestClient,
    free_tcp_port: int,
) -> None:
    """Connection errors should be surfaced as policy 1011 closes."""

    gateway_app.state.runner_ws_proxy.connect_timeout = 0.1
    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "ws_endpoint": f"ws://127.0.0.1:{free_tcp_port}/ws",
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with gateway_client.websocket_connect(
            f"/sessions/{session_id}/ws?token=dummy"
        ):
            pass
    assert exc_info.value.code == status.WS_1011_INTERNAL_ERROR
