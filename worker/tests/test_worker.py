from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from camofleet_worker.config import WorkerSettings
from camofleet_worker.main import create_app


class StubRunner:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.sessions: dict[str, dict[str, Any]] = {}

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "checks": {"runner": "ok"}}

    async def list_sessions(self) -> list[dict[str, Any]]:
        return list(self.sessions.values())

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created.append(payload)
        data = {
            "id": "sess-1",
            "status": "READY",
            "created_at": "2024-01-01T00:00:00Z",
            "last_seen_at": "2024-01-01T00:00:00Z",
            "headless": payload.get("headless", False),
            "idle_ttl_seconds": payload.get("idle_ttl_seconds", 300),
            "labels": payload.get("labels", {}),
            "vnc": payload.get("vnc", False),
            "start_url_wait": payload.get("start_url_wait", "load"),
            "ws_endpoint": "ws://runner/session",
            "vnc_info": {"ws": None, "http": None, "password_protected": False},
        }
        self.sessions[data["id"]] = data
        return data

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return self.sessions[session_id]

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        data = self.sessions.pop(session_id)
        return {"id": data["id"], "status": "DEAD"}

    async def touch_session(self, session_id: str) -> dict[str, Any]:
        data = self.sessions[session_id]
        data["last_seen_at"] = "2024-01-01T00:05:00Z"
        return data

    async def close(self) -> None:
        return None


@pytest.fixture()
def stub_app() -> TestClient:
    settings = WorkerSettings(runner_base_url="http://runner", supports_vnc=False)
    app = create_app(settings)
    state = app.state.app_state
    stub = StubRunner()
    state.runner = stub
    client = TestClient(app)
    client.runner_stub = stub  # type: ignore[attr-defined]
    return client


def test_create_session_rejects_vnc_when_not_supported(stub_app: TestClient) -> None:
    response = stub_app.post("/sessions", json={"vnc": True})
    assert response.status_code == 400


def test_create_and_list_session(stub_app: TestClient) -> None:
    response = stub_app.post("/sessions", json={"start_url": "https://example.org"})
    assert response.status_code == 201
    body = response.json()
    assert body["browser"] == "camoufox"
    assert body["ws_endpoint"].endswith("/sess-1/ws")
    assert body["start_url_wait"] == "load"

    list_resp = stub_app.get("/sessions")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["id"] == "sess-1"
    assert stub_app.runner_stub.created[0]["start_url"] == "https://example.org"


def test_get_session_returns_detail(stub_app: TestClient) -> None:
    stub_app.post("/sessions", json={"start_url": "https://example.org"})

    response = stub_app.get("/sessions/sess-1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sess-1"
    assert body["worker_id"]


def test_touch_session_updates_last_seen(stub_app: TestClient) -> None:
    stub_app.post("/sessions", json={"start_url": "https://example.org"})

    response = stub_app.post("/sessions/sess-1/touch")
    assert response.status_code == 200
    body = response.json()
    assert body["last_seen_at"] == "2024-01-01T00:05:00Z"


def test_delete_session_removes_from_store(stub_app: TestClient) -> None:
    stub_app.post("/sessions", json={"start_url": "https://example.org"})

    response = stub_app.delete("/sessions/sess-1")
    assert response.status_code == 200
    assert response.json()["status"] == "DEAD"

    list_resp = stub_app.get("/sessions")
    assert list_resp.status_code == 200
    assert list_resp.json() == []
