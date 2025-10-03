"""Integration-style tests for the gateway FastAPI application."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt
from starlette import status
from starlette.responses import StreamingResponse
from starlette.types import Scope
from starlette.websockets import WebSocket as StarletteWebSocket, WebSocketDisconnect
from unittest.mock import AsyncMock
from uuid import UUID

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app import create_app  # noqa: E402
from app.config import GatewaySettings  # noqa: E402
from app.deps import get_vnc_token_service  # noqa: E402
from app.deps.security import get_authenticator, get_current_user  # noqa: E402
from app.security import (  # noqa: E402
    AuthenticatedUser,
    AuthenticationError,
    KeycloakAuthenticator,
    VncTokenService,
)
from app.services.runner_client import RunnerCommandClient  # noqa: E402
from app.services.runner_health import RunnerHealthClient  # noqa: E402
from app.services.runner_registry import RunnerRegistry  # noqa: E402
from core import (  # noqa: E402
    Runner,
    Session,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    SessionVncDetails,
)
from tests.conftest import HttpxMockTransport  # noqa: E402

if TYPE_CHECKING:
    from .conftest import HttpxMockTransport


@pytest.fixture()
def gateway_app() -> FastAPI:
    """Return a FastAPI application with testing dependencies configured."""

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

    return app


@pytest.fixture()
def gateway_client(gateway_app: FastAPI) -> TestClient:
    """Return a FastAPI test client with dependencies overridden for testing."""

    client = TestClient(gateway_app)
    yield client
    client.close()


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO tests to run on asyncio to avoid optional trio dependency."""

    return "asyncio"


def test_session_crud(gateway_client: TestClient) -> None:
    """Sessions can be created, listed, touched, and deleted."""

    now = datetime.now(tz=UTC)
    session_body = {
        "id": str(uuid4()),
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "ws_endpoint": "ws://runner-1/playwright/1",
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    payload = response.json()
    session_id = payload["id"]
    assert payload["ws_endpoint"] == "ws://runner-1/playwright/1"
    assert payload["ws_public_endpoint"] == f"/sessions/{session_id}/ws"

    response = gateway_client.get("/sessions")
    assert response.status_code == 200
    assert any(item["id"] == session_id for item in response.json())

    proxy_body = {"http": "http://proxy", "https": None, "socks": None}
    response = gateway_client.post(f"/sessions/{session_id}/proxy", json=proxy_body)
    assert response.status_code == 200
    assert response.json()["proxy"]["http"].startswith("http://proxy")

    updated_at = (now + timedelta(seconds=30)).isoformat()
    response = gateway_client.post(f"/sessions/{session_id}/touch", json={"timestamp": updated_at})
    assert response.status_code == 200
    assert response.json()["last_seen_at"].startswith(updated_at[:19])

    response = gateway_client.delete(f"/sessions/{session_id}")
    assert response.status_code == 204

    response = gateway_client.get(f"/sessions/{session_id}")
    assert response.status_code == 404


def test_vnc_token_generation(gateway_client: TestClient) -> None:
    """Sessions containing VNC details receive signed short-lived tokens."""

    now = datetime.now(tz=UTC)
    session_body = {
        "id": str(uuid4()),
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "vnc": {"http_url": "https://vnc.example/view"},
        "ws_endpoint": "ws://runner-1/playwright/2",
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    payload = response.json()["vnc"]
    assert payload["token_ttl_seconds"] == 120
    claims = jwt.decode(payload["token"], "unit-test-secret", algorithms=["HS256"])
    assert claims["sid"] == session_body["id"]


def test_session_listing_refreshes_vnc_token_after_ttl(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """Gateway reissues VNC tokens for listings once the TTL elapses."""

    gateway_app.state.vnc_tokens._ttl_seconds = 1

    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "vnc": {"http_url": "https://vnc.example/view"},
        "ws_endpoint": "ws://runner-1/playwright/3",
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201

    listing = gateway_client.get("/sessions")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload, "Expected at least one session in listing"
    first_token = next(
        (
            item["vnc"]["token"]
            for item in payload
            if item["id"] == session_id and item.get("vnc") is not None
        ),
        None,
    )
    assert first_token is not None

    time.sleep(1.1)

    refreshed = gateway_client.get("/sessions")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    refreshed_token = next(
        (
            item["vnc"]["token"]
            for item in refreshed_payload
            if item["id"] == session_id and item.get("vnc") is not None
        ),
        None,
    )
    assert refreshed_token is not None

    assert refreshed_token != first_token


def test_vnc_overrides_apply_runner_templates(gateway_client: TestClient) -> None:
    """Runner-provided VNC templates are substituted with the session identifier."""

    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "vnc": {
            "http_url": "http://127.0.0.1:6901/view",  # runner-local endpoint
            "websocket_url": "ws://127.0.0.1:6901/ws",
        },
        "ws_endpoint": "ws://runner-1/playwright/3",
    }

    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    payload = response.json()["vnc"]
    http_url = urlparse(payload["http_url"])
    ws_url = urlparse(payload["websocket_url"])
    assert http_url.scheme == "https"
    assert ws_url.scheme == "wss"
    assert http_url.path == f"/view/{session_id}"
    assert ws_url.path == f"/ws/{session_id}"
    token_params = parse_qs(http_url.query)
    assert "token" in token_params
    assert ws_url.query == http_url.query
    assert token_params["token"][0] == payload["token"]
    assert payload["token_ttl_seconds"] == 120


@pytest.mark.anyio("asyncio")
async def test_lifespan_restores_sessions_from_healthy_runners() -> None:
    """Gateway lifespan should recover active sessions during startup."""

    now = datetime.now(tz=UTC)
    session_id = uuid4()
    session_payload = {
        "id": str(session_id),
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "labels": {"region": "eu-central"},
        "ws_endpoint": "ws://runner-1/playwright/1",
    }
    list_requests: list[httpx.Request] = []

    def _list_handler(request: httpx.Request) -> httpx.Response:
        list_requests.append(request)
        assert request.url.path == "/sessions"
        return httpx.Response(200, json=[session_payload])

    health_requests: list[httpx.Request] = []

    def _health_handler(request: httpx.Request) -> httpx.Response:
        health_requests.append(request)
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "runner_id": "runner-1",
                "slots": {"total": 1, "available": 0},
                "vnc": {"enabled": True},
            },
        )

    settings = GatewaySettings(
        discovery_mode="static",
        runners=[
            Runner(
                id="runner-1",
                base_url="http://runner-1",
                total_slots=1,
                supports_vnc=True,
            )
        ],
        jwt_jwks_url="http://jwks.local",
        vnc_token_secret="unit-test-secret",
        vnc_token_ttl_seconds=120,
    )
    app = create_app(settings)
    app.state.runner_client = RunnerCommandClient(transport=httpx.MockTransport(_list_handler))
    app.state.runner_health_client = RunnerHealthClient(
        transport=httpx.MockTransport(_health_handler)
    )

    async with app.router.lifespan_context(app):
        stored = await app.state.session_registry.list()
        assert len(stored) == 1
        session = stored[0]
        assert session.id == session_id
        assert session.runner_id == "runner-1"
        assert session.ws_endpoint == "ws://runner-1/playwright/1"
        public = await app.state.runner_registry.resolve_session_ws_public(session.id)
        assert public == f"/sessions/{session_id}/ws"

    assert [request.url.path for request in list_requests] == ["/sessions"]
    if health_requests:
        assert [request.url.path for request in health_requests] == ["/health"]


def test_session_reads_reflect_runner_override_updates(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """Stored sessions adopt runner override changes on subsequent reads."""

    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "vnc": {
            "http_url": "http://127.0.0.1:6901/view",
            "websocket_url": "ws://127.0.0.1:6901/ws",
        },
        "ws_endpoint": "ws://runner-1/playwright/4",
    }

    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    initial = response.json()["vnc"]
    initial_http = urlparse(initial["http_url"])
    initial_ws = urlparse(initial["websocket_url"])
    assert initial_http.scheme == "https"
    assert initial_ws.scheme == "wss"
    assert initial_http.path == f"/view/{session_id}"
    assert initial_ws.path == f"/ws/{session_id}"
    initial_query = parse_qs(initial_http.query)
    assert "token" in initial_query
    assert initial_ws.query == initial_http.query
    assert initial_query["token"][0] == initial["token"]

    registry = gateway_app.state.runner_registry
    runner = asyncio.run(registry.get("runner-1"))
    assert runner is not None
    asyncio.run(
        registry.upsert(
            runner.model_copy(
                update={
                    "vnc_http_url_template": "https://override.example/custom/{id}",
                    "vnc_ws_url_template": "wss://override.example/ws/{id}",
                }
            )
        )
    )

    detail = gateway_client.get(f"/sessions/{session_id}")
    assert detail.status_code == 200
    payload = detail.json()["vnc"]
    http_parts = urlparse(payload["http_url"])
    ws_parts = urlparse(payload["websocket_url"])
    assert http_parts.scheme == "https"
    assert ws_parts.scheme == "wss"
    http_segments = [segment for segment in http_parts.path.split("/") if segment]
    assert len(http_segments) >= 2
    assert http_segments[0] == "custom"
    assert http_segments[1] == session_id
    assert ws_parts.path == f"/ws/{session_id}"
    http_query = parse_qs(http_parts.query)
    assert "token" in http_query
    assert ws_parts.query == http_parts.query
    assert http_query["token"][0] == payload["token"]

    listing = gateway_client.get("/sessions")
    assert listing.status_code == 200
    sessions = listing.json()
    entry = next(item for item in sessions if item["id"] == session_id)
    list_http = urlparse(entry["vnc"]["http_url"])
    list_ws = urlparse(entry["vnc"]["websocket_url"])
    list_http_segments = [segment for segment in list_http.path.split("/") if segment]
    assert len(list_http_segments) >= 2
    assert list_http_segments[0] == "custom"
    assert list_http_segments[1] == session_id
    assert list_ws.path == f"/ws/{session_id}"
    list_query = parse_qs(list_http.query)
    assert "token" in list_query
    assert list_ws.query == list_http.query
    assert list_query["token"][0] == entry["vnc"]["token"]


def test_create_command_proxies_to_runner(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """Command endpoint issues POST to the runner and stores the response."""

    now = datetime.now(tz=UTC)
    session_id = uuid4()
    session = Session(
        id=session_id,
        runner_id="runner-1",
        status=SessionStatus.INIT,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        labels={"region": "eu-central", "proxy_id": "proxy-1"},
    )
    recorded: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(201, json=session.model_dump(mode="json"))

    gateway_app.state.runner_client = RunnerCommandClient(
        transport=httpx.MockTransport(_handler)
    )

    response = gateway_client.post(
        "/sessions/commands",
        json={
            "runner_id": "runner-1",
            "browser_name": "Chrome",
            "region": "eu-central",
            "proxy_id": "proxy-1",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == str(session_id)
    assert payload["labels"]["region"] == "eu-central"
    assert recorded and recorded[0].method == "POST"
    assert recorded[0].url.path == "/sessions"

    sessions = gateway_client.get("/sessions").json()
    assert any(item["id"] == str(session_id) for item in sessions)


def test_runners_endpoint_exposes_health_snapshot(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """The runners endpoint should surface health metadata from the registry."""

    now = datetime.now(tz=UTC)
    registry = gateway_app.state.runner_registry
    asyncio.run(registry.record_health("runner-1", healthy=False, heartbeat_at=now))

    response = gateway_client.get("/runners")
    assert response.status_code == 200
    payload = response.json()
    assert payload and payload[0]["healthy"] is False
    assert payload[0]["last_heartbeat_at"].startswith(now.isoformat()[:19])


def test_create_command_returns_503_when_no_vnc_runner_available(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """Selecting a runner should fail when no healthy VNC-capable runner exists."""

    registry = gateway_app.state.runner_registry
    asyncio.run(
        registry.upsert(
            Runner(
                id="runner-2",
                base_url="http://runner-2",
                total_slots=1,
                supports_vnc=False,
            )
        )
    )
    asyncio.run(
        registry.record_health(
            "runner-1", healthy=False, heartbeat_at=datetime.now(tz=UTC)
        )
    )

    response = gateway_client.post(
        "/sessions/commands",
        json={
            "browser_name": "Chrome",
            "region": "eu-central",
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "No healthy runners available"


def test_update_command_mirrors_runner_changes(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """PATCH command updates the registry with the runner response."""

    now = datetime.now(tz=UTC)
    session_id = uuid4()
    base_session = {
        "id": str(session_id),
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
    }
    assert gateway_client.post("/sessions", json=base_session).status_code == 201

    updated = Session(
        id=session_id,
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )
    recorded: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=updated.model_dump(mode="json"))

    gateway_app.state.runner_client = RunnerCommandClient(
        transport=httpx.MockTransport(_handler)
    )

    response = gateway_client.patch(
        f"/sessions/commands/{session_id}",
        json={"status": SessionStatus.READY.value},
    )
    assert response.status_code == 200
    assert response.json()["status"] == SessionStatus.READY.value
    assert recorded and recorded[0].method == "PATCH"
    payload = json.loads(recorded[0].content.decode())
    assert payload == {"status": SessionStatus.READY.value}

    lookup = gateway_client.get(f"/sessions/{session_id}")
    assert lookup.status_code == 200
    assert lookup.json()["status"] == SessionStatus.READY.value


def test_delete_command_removes_session(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """DELETE command proxies to the runner and purges the registry."""

    now = datetime.now(tz=UTC)
    session_id = uuid4()
    base_session = {
        "id": str(session_id),
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
    }
    assert gateway_client.post("/sessions", json=base_session).status_code == 201

    terminated = Session(
        id=session_id,
        runner_id="runner-1",
        status=SessionStatus.DEAD,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        ended_at=now,
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=terminated.model_dump(mode="json"))

    gateway_app.state.runner_client = RunnerCommandClient(
        transport=httpx.MockTransport(_handler)
    )

    response = gateway_client.delete(f"/sessions/commands/{session_id}")
    assert response.status_code == 200
    assert response.json()["status"] == SessionStatus.DEAD.value

    assert gateway_client.get(f"/sessions/{session_id}").status_code == 404


def test_delete_command_drops_ws_binding(
    gateway_app: FastAPI, gateway_client: TestClient
) -> None:
    """DELETE command clears the runner WebSocket binding when completed."""

    session_id = uuid4()
    now = datetime.now(tz=UTC)
    base_session = {
        "id": str(session_id),
        "runner_id": "runner-1",
        "status": SessionStatus.READY.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
    }
    assert gateway_client.post("/sessions", json=base_session).status_code == 201

    delegate = gateway_app.state.runner_registry

    class _RunnerRegistryProbe:
        """Proxy registry forwarding calls while spying on drops."""

        def __init__(self, inner: RunnerRegistry) -> None:
            self._inner = inner
            original_drop = inner.drop_session_ws_endpoint

            async def _side_effect(target_session_id: UUID) -> None:
                await original_drop(target_session_id)

            self.drop_session_ws_endpoint = AsyncMock(side_effect=_side_effect)

        async def get(self, runner_id: str) -> Runner | None:
            return await self._inner.get(runner_id)

        async def register_session_ws_endpoint(
            self,
            session_id: UUID,
            *,
            runner_id: str,
            target: str | None,
        ) -> str | None:
            return await self._inner.register_session_ws_endpoint(
                session_id,
                runner_id=runner_id,
                target=target,
            )

        async def resolve_session_ws_public(self, session_id: UUID) -> str | None:
            return await self._inner.resolve_session_ws_public(session_id)

    probe = _RunnerRegistryProbe(delegate)
    gateway_app.state.runner_registry = probe

    terminated = Session(
        id=session_id,
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    ).model_copy(
        update={
            "status": SessionStatus.DEAD,
            "ended_at": now,
        }
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=terminated.model_dump(mode="json"))

    gateway_app.state.runner_client = RunnerCommandClient(
        transport=httpx.MockTransport(_handler)
    )

    try:
        response = gateway_client.delete(f"/sessions/commands/{session_id}")
    finally:
        gateway_app.state.runner_registry = delegate

    assert response.status_code == 200
    probe.drop_session_ws_endpoint.assert_awaited_once_with(session_id)


def test_vnc_token_service_enriches_missing_token() -> None:
    """``enrich_vnc_details`` must mint a token whenever one is absent."""

    service = VncTokenService(secret="secret", ttl_seconds=90)
    details = SessionVncDetails(http_url="https://viewer.example/session")

    enriched = service.enrich_vnc_details(details, session_id="session-1", subject="user")

    assert enriched.token is not None
    assert enriched.token_ttl_seconds == 90
    assert enriched is not details


@pytest.mark.anyio("asyncio")
async def test_sse_accepts_access_token_query_parameter(gateway_app: FastAPI) -> None:
    """SSE authentication falls back to the ``access_token`` query parameter."""

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/events",
        "headers": [],
        "query_string": b"access_token=test-token",
    }
    request = Request(scope)
    authenticator = gateway_app.state.authenticator

    user = await get_current_user(
        request=request,
        credentials=None,
        authenticator=authenticator,
        settings=gateway_app.state.settings,
    )
    assert user.subject == "tester"


@pytest.mark.anyio("asyncio")
async def test_sse_event_forwarding(gateway_app: FastAPI) -> None:
    """Events published into the bridge appear on the SSE endpoint."""

    from app.routers.events import publish_session_event, stream_events

    bridge = gateway_app.state.event_bridge
    now = datetime.now(tz=UTC)
    session = Session(
        id=uuid4(),
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )
    event = SessionEvent(
        session=session,
        occurred_at=now,
        type=SessionEventType.UPDATED,
    )

    response = await stream_events(
        bridge=bridge,
        user=AuthenticatedUser(subject="tester", email="tester@example.com"),
    )
    assert isinstance(response, StreamingResponse)

    iterator = response.body_iterator
    consumer = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)
    result = await publish_session_event(
        event=event,
        bridge=bridge,
        _user=AuthenticatedUser(subject="tester", email="tester@example.com"),
    )
    assert result.status_code == 202
    chunk = await asyncio.wait_for(consumer, timeout=1)
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    payload = json.loads(text.removeprefix("data:").strip())
    assert payload["session"]["id"] == str(event.session.id)
    await iterator.aclose()


@pytest.mark.anyio("asyncio")
async def test_mutation_endpoints_emit_session_events(gateway_app: FastAPI) -> None:
    """Gateway-managed mutations should notify subscribers via the bridge."""

    bridge = gateway_app.state.event_bridge
    subscription = await bridge.subscribe()
    now = datetime.now(tz=UTC)
    session_id = str(uuid4())
    session_body = {
        "id": session_id,
        "runner_id": "runner-1",
        "status": SessionStatus.INIT.value,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "headless": False,
        "idle_ttl_seconds": 300,
        "ws_endpoint": "ws://runner-1/playwright/5",
    }
    transport = httpx.ASGITransport(app=gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/sessions", json=session_body)
        assert response.status_code == 201
        created_event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert created_event.type is SessionEventType.CREATED

        proxy_payload = {"http": "http://proxy", "https": None, "socks": None}
        response = await client.post(f"/sessions/{session_id}/proxy", json=proxy_payload)
        assert response.status_code == 200
        proxy_event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert proxy_event.type is SessionEventType.UPDATED

        heartbeat_payload = {"timestamp": (now + timedelta(seconds=30)).isoformat()}
        response = await client.post(f"/sessions/{session_id}/touch", json=heartbeat_payload)
        assert response.status_code == 200
        touch_event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert touch_event.type is SessionEventType.UPDATED

        response = await client.delete(f"/sessions/{session_id}")
        assert response.status_code == 204
        delete_event = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert delete_event.type is SessionEventType.ENDED

    await subscription.aclose()


def test_websocket_event_forwarding(gateway_client: TestClient) -> None:
    """Events are also forwarded to WebSocket subscribers."""

    now = datetime.now(tz=UTC)
    session = Session(
        id=uuid4(),
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )
    event = SessionEvent(
        session=session,
        occurred_at=now,
        type=SessionEventType.UPDATED,
    )
    with gateway_client.websocket_connect("/events/ws?token=stub") as websocket:
        response = gateway_client.post(
            "/events",
            json=event.model_dump(mode="json", by_alias=True),
        )
        assert response.status_code == 202
        message = websocket.receive_json()
        assert message["session"]["id"] == str(session.id)


def test_websocket_event_invalid_token_closes_without_server_error(
    gateway_app: FastAPI,
    gateway_client: TestClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejecting authentication should close once with 1008 and avoid server errors."""

    close_codes: list[int] = []
    original_close = StarletteWebSocket.close

    async def tracking_close(self: StarletteWebSocket, *args, **kwargs) -> None:
        code = kwargs.get("code")
        if code is None and args:
            code = args[0]
        if code is None:
            code = status.WS_1000_NORMAL_CLOSURE
        close_codes.append(code)
        await original_close(self, *args, **kwargs)

    monkeypatch.setattr(StarletteWebSocket, "close", tracking_close)

    class _RejectingAuthenticator:
        async def authenticate(self, token: str) -> AuthenticatedUser:
            """Always reject the provided bearer token for the test."""

            raise AuthenticationError("invalid token")

    authenticator = _RejectingAuthenticator()
    gateway_app.state.authenticator = authenticator
    gateway_app.dependency_overrides[get_authenticator] = lambda: authenticator

    caplog.set_level(logging.ERROR)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with gateway_client.websocket_connect("/events/ws?token=invalid"):
            pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert close_codes == [status.WS_1008_POLICY_VIOLATION]
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []


@pytest.mark.anyio
async def test_keycloak_authenticator_logs_subject(
    httpx_mock_transport: HttpxMockTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The authenticator validates a token using JWKS metadata and logs the subject."""

    authenticator = KeycloakAuthenticator("http://jwks")
    secret = "shared-secret"
    jwk_entry = {
        "kty": "oct",
        "kid": "unit",
        "k": base64.urlsafe_b64encode(secret.encode("utf-8")).decode("utf-8").rstrip("="),
        "alg": "HS256",
    }
    httpx_mock_transport.enqueue_json({"keys": [jwk_entry]})
    caplog.set_level("INFO", logger="gateway.security")
    payload = {
        "sub": "subject-1",
        "email": "subject@example.com",
        "exp": int((datetime.now(tz=UTC) + timedelta(minutes=5)).timestamp()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256", headers={"kid": "unit"})
    user = await authenticator.authenticate(token)
    assert user.subject == "subject-1"
    assert any(record.sub == "subject-1" for record in caplog.records)


@pytest.mark.anyio
async def test_keycloak_authenticator_fetches_and_caches_jwks(
    httpx_mock_transport: HttpxMockTransport,
) -> None:
    """Keycloak authenticator caches JWKS and retries on cache misses or errors."""

    authenticator = KeycloakAuthenticator("http://jwks")
    first_key = {
        "kty": "RSA",
        "kid": "first",
        "n": "AQAB",
        "e": "AQAB",
    }
    httpx_mock_transport.enqueue_json({"keys": [first_key]})
    cached = await authenticator._get_key("first")
    assert cached == first_key
    assert len(httpx_mock_transport.requests) == 1

    cached_again = await authenticator._get_key("first")
    assert cached_again == first_key
    assert len(httpx_mock_transport.requests) == 1

    second_key = {
        "kty": "RSA",
        "kid": "second",
        "n": "AQAC",
        "e": "AQAC",
    }
    httpx_mock_transport.enqueue_json({"keys": [second_key]})
    refreshed = await authenticator._get_key("second")
    assert refreshed == second_key
    assert len(httpx_mock_transport.requests) == 2

    httpx_mock_transport.enqueue_json({"keys": []}, status_code=500)
    with pytest.raises(httpx.HTTPStatusError):
        await authenticator._fetch_jwks()
    assert len(httpx_mock_transport.requests) == 3

    httpx_mock_transport.enqueue_text("not-a-json-payload")
    with pytest.raises(ValueError):
        await authenticator._fetch_jwks()
    assert len(httpx_mock_transport.requests) == 4
