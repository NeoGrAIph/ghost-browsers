"""Unit tests for the gateway service."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import anyio
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt
from starlette.responses import StreamingResponse
from starlette.types import Scope

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app import create_app  # noqa: E402
from app.config import GatewaySettings  # noqa: E402
from app.deps import get_vnc_token_service  # noqa: E402
from app.deps.security import get_authenticator, get_current_user  # noqa: E402
from app.security import AuthenticatedUser, KeycloakAuthenticator, VncTokenService  # noqa: E402
from app.services.runner_client import RunnerCommandClient  # noqa: E402
from core import (
    Runner,
    Session,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    SessionVncDetails,
)  # noqa: E402


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
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    session_id = response.json()["id"]

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
    }
    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    payload = response.json()["vnc"]
    assert payload["token_ttl_seconds"] == 120
    claims = jwt.decode(payload["token"], "unit-test-secret", algorithms=["HS256"])
    assert claims["sid"] == session_body["id"]


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
    }

    response = gateway_client.post("/sessions", json=session_body)
    assert response.status_code == 201
    payload = response.json()["vnc"]
    assert payload["http_url"] == f"https://vnc.example/view/{session_id}"
    assert payload["websocket_url"] == f"wss://vnc.example/ws/{session_id}"
    assert payload["token"]
    assert payload["token_ttl_seconds"] == 120


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

    user = await get_current_user(request=request, credentials=None, authenticator=authenticator)
    assert user.subject == "tester"


@pytest.mark.anyio("asyncio")
async def test_sse_event_forwarding(gateway_app: FastAPI) -> None:
    """Events published into the bridge appear on the SSE endpoint."""

    from app.routers.events import stream_events

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
    await bridge.publish(event)
    chunk = await asyncio.wait_for(consumer, timeout=1)
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
    payload = json.loads(text.removeprefix("data:").strip())
    assert payload["session"]["id"] == str(event.session.id)
    await iterator.aclose()


def test_websocket_event_forwarding(gateway_client: TestClient) -> None:
    """Events are also forwarded to WebSocket subscribers."""

    bridge = gateway_client.app.state.event_bridge
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
    anyio.run(bridge.publish, event)
    with gateway_client.websocket_connect("/events/ws?token=stub") as websocket:
        message = websocket.receive_json()
        assert message["session"]["id"] == str(session.id)


@pytest.mark.anyio
async def test_keycloak_authenticator_logs_subject(caplog: pytest.LogCaptureFixture) -> None:
    """The authenticator validates a token using JWKS metadata and logs the subject."""

    authenticator = KeycloakAuthenticator("http://jwks")
    secret = "shared-secret"
    jwk_entry = {
        "kty": "oct",
        "kid": "unit",
        "k": base64.urlsafe_b64encode(secret.encode("utf-8")).decode("utf-8").rstrip("="),
        "alg": "HS256",
    }
    authenticator._jwks_cache = {"unit": jwk_entry}  # type: ignore[attr-defined]
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
