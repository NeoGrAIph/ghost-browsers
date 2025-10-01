"""Unit tests for the VNC gateway FastAPI application."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve()
REPO_ROOT = TEST_ROOT.parents[3]
GATEWAY_APP_ROOT = REPO_ROOT / "services" / "gateway" / "app"
CORE_PACKAGE_ROOT = REPO_ROOT / "packages" / "core"

for path in (REPO_ROOT, GATEWAY_APP_ROOT, CORE_PACKAGE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.dependencies import get_runner_proxy, get_token_validator
from camou_vnc_gateway.main import create_app
from camou_vnc_gateway.token import TokenValidationError, TokenValidator
from fastapi import Request
from fastapi.testclient import TestClient
from jose import jwt
from security.vnc import VncTokenService


class DummyRunnerProxy:
    """Deterministic runner proxy used for unit tests."""

    def __init__(self) -> None:
        self.http_calls: list[tuple[str, Request]] = []
        self.ws_sessions: list[str] = []

    async def forward_http(self, *, session_id: str, request: Request):
        self.http_calls.append((session_id, request))
        return {"session": session_id}

    async def forward_websocket(self, *, session_id: str, websocket):
        self.ws_sessions.append(session_id)
        await websocket.accept()
        await websocket.close()


@pytest.fixture()
def settings() -> Settings:
    """Provide static settings used across tests."""

    return Settings(token_secret="top-secret", runner_http_base="http://runner", runner_ws_base="ws://runner")


@pytest.fixture()
def validator(settings: Settings) -> TokenValidator:
    """Expose a token validator bound to the fixture settings."""

    return TokenValidator(secret=settings.token_secret)


@pytest.fixture()
def token_service(settings: Settings) -> VncTokenService:
    """Return a token issuer aligned with the validator configuration."""

    return VncTokenService(secret=settings.token_secret, ttl_seconds=60)


@pytest.fixture()
def app(settings: Settings, validator: TokenValidator):
    """Create a FastAPI app with stubbed dependencies."""

    application = create_app(settings=settings)
    runner_proxy = DummyRunnerProxy()

    application.dependency_overrides[get_token_validator] = lambda: validator
    application.dependency_overrides[get_runner_proxy] = lambda: runner_proxy
    application.state.runner_proxy = runner_proxy
    return application


def test_token_validator_success(validator: TokenValidator, token_service: VncTokenService) -> None:
    """Validator accepts a properly signed token."""

    session_id = "abc"
    token, _ = token_service.issue(session_id)
    validator.validate(session_id, token)


def test_token_validator_rejects_invalid_signature(validator: TokenValidator, token_service: VncTokenService) -> None:
    """Validation fails when the signature portion is invalid."""

    session_id = "abc"
    token, _ = token_service.issue(session_id)
    token = token[:-2] + "ab"
    with pytest.raises(TokenValidationError):
        validator.validate(session_id, token)


def test_token_validator_rejects_wrong_session(validator: TokenValidator, token_service: VncTokenService) -> None:
    """Tokens scoped to another session are rejected."""

    token, _ = token_service.issue("session-a")
    with pytest.raises(TokenValidationError):
        validator.validate("session-b", token)


def test_token_validator_rejects_expired_token(validator: TokenValidator, settings: Settings) -> None:
    """Expired JWT tokens are rejected."""

    expired_at = datetime.now(tz=UTC) - timedelta(seconds=5)
    token = jwt.encode(
        {
            "sid": "session-expired",
            "iss": "camou-gateway",
            "exp": int(expired_at.timestamp()),
        },
        settings.token_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenValidationError):
        validator.validate("session-expired", token)


def test_http_endpoint_proxies_request(app, token_service: VncTokenService) -> None:
    """HTTP endpoint validates token and forwards to the proxy."""

    client = TestClient(app)
    token, _ = token_service.issue("session-1")
    response = client.get("/sessions/session-1", headers={"X-VNC-Token": token})
    assert response.status_code == 200
    assert response.json() == {"session": "session-1"}
    runner_proxy: DummyRunnerProxy = app.state.runner_proxy
    assert runner_proxy.http_calls[0][0] == "session-1"


def test_http_endpoint_rejects_missing_token(app) -> None:
    """Requests without the token header are denied."""

    client = TestClient(app)
    response = client.get("/sessions/123")
    assert response.status_code == 401


def test_websocket_endpoint_invokes_proxy(app, token_service: VncTokenService) -> None:
    """WebSocket endpoint triggers the proxy when token is valid."""

    client = TestClient(app)
    token, _ = token_service.issue("session-ws")
    with client.websocket_connect("/sessions/session-ws/ws", headers={"X-VNC-Token": token}):
        pass
    runner_proxy: DummyRunnerProxy = app.state.runner_proxy
    assert runner_proxy.ws_sessions == ["session-ws"]
