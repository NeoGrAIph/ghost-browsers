"""Authentication tests for the event publication endpoint."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from ipaddress import ip_network
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, status

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app import create_app  # noqa: E402
from app.config import GatewaySettings  # noqa: E402
from app.security import AuthenticatedUser  # noqa: E402
from core import Session, SessionEvent, SessionEventType, SessionStatus  # noqa: E402


@pytest.fixture()
def secured_gateway_app() -> FastAPI:
    """Return a gateway app instrumented with a deterministic authenticator."""

    settings = GatewaySettings(
        discovery_mode="static",
        jwt_jwks_url="http://jwks.local",
        vnc_token_secret="unit-test-secret",
        vnc_token_ttl_seconds=60,
        trusted_cidrs=[ip_network("10.0.0.0/8")],
    )
    app = create_app(settings)

    class DummyAuthenticator:
        """Authenticator stub returning a fixed user for valid tokens."""

        async def authenticate(self, token: str) -> AuthenticatedUser:
            """Return the synthetic user used for authorisation tests."""

            return AuthenticatedUser(subject="token-user", email="token@example.com")

    app.state.authenticator = DummyAuthenticator()
    return app


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO-powered tests to execute on the asyncio backend."""

    return "asyncio"


def _build_event_payload() -> tuple[dict[str, Any], SessionEvent]:
    """Create a serialisable session event and its originating model."""

    now = datetime.now(tz=UTC)
    session = Session(
        id=uuid4(),
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        ws_endpoint="ws://runner-1/playwright/stream",
    )
    event = SessionEvent(
        session=session,
        occurred_at=now,
        type=SessionEventType.UPDATED,
    )
    payload = event.model_dump(mode="json", by_alias=True)
    return payload, event


@pytest.mark.anyio("asyncio")
async def test_publish_session_event_rejects_unauthenticated_callers(
    secured_gateway_app: FastAPI,
) -> None:
    """POST /events should fail when no credentials are supplied."""

    payload, _ = _build_event_payload()
    transport = httpx.ASGITransport(app=secured_gateway_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/events", json=payload)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio("asyncio")
async def test_publish_session_event_accepts_authenticated_callers(
    secured_gateway_app: FastAPI,
) -> None:
    """POST /events should succeed for authenticated callers and publish the event."""

    payload, event = _build_event_payload()
    bridge = secured_gateway_app.state.event_bridge
    subscription = await bridge.subscribe()
    transport = httpx.ASGITransport(app=secured_gateway_app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/events",
                json=payload,
                headers={"Authorization": "Bearer good-token"},
            )

        assert response.status_code == status.HTTP_202_ACCEPTED
        published = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert published.session.id == event.session.id
    finally:
        await subscription.aclose()


@pytest.mark.anyio("asyncio")
async def test_publish_session_event_allows_trusted_network_bypass(
    secured_gateway_app: FastAPI,
) -> None:
    """POST /events should accept trusted network calls without bearer tokens."""

    payload, event = _build_event_payload()
    bridge = secured_gateway_app.state.event_bridge
    subscription = await bridge.subscribe()
    transport = httpx.ASGITransport(app=secured_gateway_app, client=("10.1.2.3", 12345))

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/events", json=payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        published = await asyncio.wait_for(subscription.__anext__(), timeout=1)
        assert published.session.id == event.session.id
    finally:
        await subscription.aclose()
