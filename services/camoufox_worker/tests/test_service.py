"""Tests covering the FastAPI worker service integration."""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from worker.config import SessionDefaults, WorkerSettings
from worker import service


@pytest.fixture
def anyio_backend() -> str:
    """Constrain AnyIO-backed tests to the asyncio implementation."""

    return "asyncio"


class _StubRunnerClient:
    """Minimal stub mimicking :class:`worker.runner_client.RunnerClient`."""

    def __init__(self) -> None:
        self.created_payload: dict | None = None

    async def health(self) -> dict:
        return {"status": "ok", "checks": {"runner": "up"}}

    async def list_sessions(self) -> list[dict]:
        now = datetime.now().isoformat()
        return [
            {
                "id": "sess-1",
                "status": "READY",
                "created_at": now,
                "last_seen_at": now,
                "browser": "camoufox",
                "headless": False,
                "idle_ttl_seconds": 300,
                "labels": {},
                "vnc": {},
                "vnc_enabled": True,
                "start_url_wait": "load",
            }
        ]

    async def create_session(self, payload: dict) -> dict:
        self.created_payload = payload
        now = datetime.now().isoformat()
        return {
            "id": "sess-created",
            "status": "INIT",
            "created_at": now,
            "last_seen_at": now,
            "browser": "camoufox",
            "headless": payload.get("headless", False),
            "idle_ttl_seconds": payload.get("idle_ttl_seconds", 300),
            "labels": payload.get("labels", {}),
            "vnc": {},
            "vnc_enabled": bool(payload.get("vnc", False)),
            "start_url_wait": payload.get("start_url_wait", "load"),
        }

    async def get_session(self, session_id: str) -> dict:  # pragma: no cover - unused in tests
        raise NotImplementedError

    async def delete_session(self, session_id: str) -> dict:  # pragma: no cover - unused in tests
        raise NotImplementedError

    async def touch_session(self, session_id: str) -> dict:  # pragma: no cover - unused in tests
        raise NotImplementedError


@pytest.mark.anyio
async def test_create_session_merges_required_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubRunnerClient()
    monkeypatch.setattr(service, "RunnerClient", lambda base_url: stub)
    settings = WorkerSettings(
        runner_base_url="http://runner",
        supports_vnc=True,
        browser_required_flags={"MOZ_DISABLE_HTTP3": "1"},
        session_defaults=SessionDefaults(headless=False, idle_ttl_seconds=120, start_url_wait="load"),
    )
    app = service.create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://worker") as client:
        response = await client.post(
            "/sessions",
            json={
                "headless": True,
                "browser_flags": {"custom": "flag"},
            },
        )
    assert response.status_code == 201
    assert stub.created_payload is not None
    assert stub.created_payload["metadata"]["browser_flags"] == {
        "custom": "flag",
        "MOZ_DISABLE_HTTP3": "1",
    }
    assert stub.created_payload["idle_ttl_seconds"] == 120
    assert stub.created_payload["start_url_wait"] == "load"


@pytest.mark.anyio
async def test_create_session_rejects_vnc_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubRunnerClient()
    monkeypatch.setattr(service, "RunnerClient", lambda base_url: stub)
    settings = WorkerSettings(
        runner_base_url="http://runner",
        supports_vnc=False,
        session_defaults=SessionDefaults(),
    )
    app = service.create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://worker") as client:
        response = await client.post(
            "/sessions",
            json={"vnc": True},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "VNC is not supported by this worker"
    assert stub.created_payload is None

