"""Unit tests for the VNC gateway FastAPI application."""

from __future__ import annotations

import pytest
from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.dependencies import get_runner_proxy, get_token_validator
from camou_vnc_gateway.main import create_app
from camou_vnc_gateway.token import TokenValidationError, TokenValidator
from fastapi import Request
from fastapi.testclient import TestClient


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
def app(settings: Settings, validator: TokenValidator):
    """Create a FastAPI app with stubbed dependencies."""

    application = create_app(settings=settings)
    runner_proxy = DummyRunnerProxy()

    application.dependency_overrides[get_token_validator] = lambda: validator
    application.dependency_overrides[get_runner_proxy] = lambda: runner_proxy
    application.state.runner_proxy = runner_proxy
    return application


def test_token_validator_success(validator: TokenValidator) -> None:
    """Validator accepts a properly signed token."""

    session_id = "abc"
    token = validator.issue(session_id)
    validator.validate(session_id, token)


def test_token_validator_rejects_invalid_signature(validator: TokenValidator) -> None:
    """Validation fails when the signature portion is invalid."""

    session_id = "abc"
    token = validator.issue(session_id)[:-2] + "ab"
    with pytest.raises(TokenValidationError):
        validator.validate(session_id, token)


def test_http_endpoint_proxies_request(app, validator: TokenValidator) -> None:
    """HTTP endpoint validates token and forwards to the proxy."""

    client = TestClient(app)
    token = validator.issue("session-1")
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


def test_websocket_endpoint_invokes_proxy(app, validator: TokenValidator) -> None:
    """WebSocket endpoint triggers the proxy when token is valid."""

    client = TestClient(app)
    token = validator.issue("session-ws")
    with client.websocket_connect("/sessions/session-ws/ws", headers={"X-VNC-Token": token}):
        pass
    runner_proxy: DummyRunnerProxy = app.state.runner_proxy
    assert runner_proxy.ws_sessions == ["session-ws"]
