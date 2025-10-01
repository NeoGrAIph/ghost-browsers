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
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from starlette.responses import StreamingResponse

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app import create_app  # noqa: E402
from app.config import GatewaySettings  # noqa: E402
from app.deps import get_vnc_token_service  # noqa: E402
from app.deps.security import get_authenticator, get_current_user  # noqa: E402
from app.security import AuthenticatedUser, KeycloakAuthenticator, VncTokenService  # noqa: E402
from core import Runner, Session, SessionEvent, SessionEventType, SessionStatus  # noqa: E402


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
