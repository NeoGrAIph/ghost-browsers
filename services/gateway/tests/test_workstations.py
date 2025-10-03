"""Gateway API tests focused on workstation registration and lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app import create_app
from app.config import GatewaySettings
from app.deps.security import get_authenticator, get_current_user
from app.security import AuthenticatedUser
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def gateway_app() -> FastAPI:
    """Return a FastAPI application configured for workstation tests."""

    settings = GatewaySettings(
        discovery_mode="static",
        runners=[],
        jwt_jwks_url="http://jwks.local",
        vnc_token_ttl_seconds=60,
        vnc_token_secret="unit-test-secret",
    )
    app = create_app(settings)
    user = AuthenticatedUser(subject="tester", email="tester@example.com")

    async def _user_override() -> AuthenticatedUser:
        return user

    class _DummyAuthenticator:
        async def authenticate(self, token: str) -> AuthenticatedUser:
            return user

    dummy_auth = _DummyAuthenticator()
    app.state.authenticator = dummy_auth
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_authenticator] = lambda: dummy_auth
    return app


@pytest.fixture()
def gateway_client(gateway_app: FastAPI) -> TestClient:
    """Return a synchronous test client bound to ``gateway_app``."""

    client = TestClient(gateway_app)
    yield client
    client.close()


def test_workstation_metadata_roundtrip(gateway_client: TestClient) -> None:
    """Gateway stores and returns workstation metadata snapshots."""

    payload = {
        "workstation": {
            "id": "ws-1",
            "fingerprint_id": "fp-1",
            "state": "available",
            "metadata": {"region": "eu-central"},
            "proxy_summary": "corp proxy",
        }
    }
    response = gateway_client.post("/workstations", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["workstation"]["id"] == "ws-1"
    assert body["workstation"]["state"] == "available"
    assert body["last_event_id"] is None

    response = gateway_client.get("/workstations")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["workstation"]["fingerprint_id"] == "fp-1"

    response = gateway_client.get("/workstations/ws-1")
    assert response.status_code == 200
    assert response.json()["workstation"]["metadata"]["region"] == "eu-central"


def test_workstation_events_update_registry(gateway_client: TestClient) -> None:
    """Workstation events update the stored snapshot and record event metadata."""

    event_id = str(uuid4())
    occurred_at = datetime.now(tz=UTC).isoformat()
    event_payload = {
        "id": event_id,
        "type": "workstation.updated",
        "occurred_at": occurred_at,
        "reason": "assigned to session",
        "workstation": {
            "id": "ws-evt",
            "fingerprint_id": "fp-evt",
            "state": "assigned",
        },
    }
    response = gateway_client.post("/workstations/events", json=event_payload)
    assert response.status_code == 202
    body = response.json()
    assert body["last_event_id"] == event_id
    assert body["workstation"]["state"] == "assigned"
    assert body["last_event_reason"] == "assigned to session"

    response = gateway_client.get("/workstations/ws-evt")
    assert response.status_code == 200
    record = response.json()
    assert record["last_event_id"] == event_id
    assert record["workstation"]["fingerprint_id"] == "fp-evt"

    update_payload = {
        "workstation": {
            "id": "ws-evt",
            "fingerprint_id": "fp-evt",
            "state": "available",
            "metadata": {"note": "clean"},
        }
    }
    response = gateway_client.post("/workstations", json=update_payload)
    assert response.status_code == 201
    updated = response.json()
    assert updated["workstation"]["state"] == "available"
    assert updated["last_event_id"] == event_id


def test_get_missing_workstation_returns_404(gateway_client: TestClient) -> None:
    """Gateway reports ``404`` when the workstation does not exist."""

    response = gateway_client.get("/workstations/missing")
    assert response.status_code == 404
