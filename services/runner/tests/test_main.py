"""Unit tests for FastAPI endpoints exposed by the runner application."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import RunnerSettings
from app.dependencies.session_manager import (
    get_event_publisher,
    get_runner_settings,
    get_session_manager,
)
from app.events import InMemorySessionEventPublisher
from app.main import app
from app.session_manager import SessionCreatePayload, SessionManager


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_health_endpoint_reports_extended_metrics() -> None:
    """``GET /health`` should expose slots, proxy, VNC, and prewarm diagnostics."""

    settings = RunnerSettings(
        runner_id="runner-health",
        camoufox_path="/usr/bin/camoufox",
        slot_limit=3,
        vnc_enabled=True,
        vnc_http_base_url="http://localhost:9000/vnc",
        vnc_ws_base_url="ws://localhost:9000/vnc",
        proxy_enabled=True,
        proxy_http_base_url="http://proxy.example:3128",
        prewarm_failure_history_size=5,
    )
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(settings, publisher)

    await manager.create_session(SessionCreatePayload())
    await manager.create_session(SessionCreatePayload())
    await manager.record_prewarm_failure("prewarm timeout")
    await manager.record_prewarm_failure("prewarm retry failed")

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["runner_id"] == "runner-health"
    assert payload["camoufox_path"].endswith("camoufox")
    assert payload["slots"] == {"total": 3, "active": 2, "available": 1}
    assert payload["vnc"] == {
        "http_base_url": "http://localhost:9000/vnc",
        "ws_base_url": "ws://localhost:9000/vnc",
        "enabled": True,
    }
    assert payload["proxy"] == {
        "enabled": True,
        "http_base_url": "http://proxy.example:3128",
        "https_base_url": None,
        "socks_base_url": None,
    }
    assert payload["prewarm"] == {
        "failures": 2,
        "last_error": "prewarm retry failed",
    }
