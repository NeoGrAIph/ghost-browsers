"""Unit tests for FastAPI endpoints exposed by the runner application."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
from core.models import SessionVncDetails


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


class _MainStubHandle:
    """Minimal stub mirroring :class:`BrowserSessionHandle` for API tests."""

    def __init__(self, endpoint: str, pid: int) -> None:
        self.ws_endpoint = endpoint
        self.pid = pid

    async def shutdown(self, *, force: bool, timeout: float = 5.0) -> None:
        """Pretend to terminate the Playwright subprocess."""

        return None


class _MainStubVncHandle:
    """Lightweight VNC handle used by API-level tests."""

    def __init__(self, session_id: str) -> None:
        self.details = SessionVncDetails(
            http_url=f"http://stub-vnc/{session_id}",
            websocket_url=f"ws://stub-vnc/{session_id}",
            token=None,
            token_ttl_seconds=None,
        )

    def browser_environment(self) -> dict[str, str]:
        """Expose a fake ``DISPLAY`` environment for browsers."""

        return {"DISPLAY": ":stub"}


class _MainStubVncController:
    """Test double replacing the process-based VNC controller."""

    async def allocate(self, session_id: str) -> _MainStubVncHandle:
        """Return a deterministic handle for ``session_id``."""

        return _MainStubVncHandle(session_id)

    async def release(self, handle: _MainStubVncHandle | None) -> None:
        """No-op release hook for compatibility with the real controller."""

        return None


class _ApiStubClock:
    """Mutable clock used to produce deterministic timestamps in API tests."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def advance(self, seconds: float) -> None:
        """Advance the current timestamp by ``seconds``."""

        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        """Return the current timestamp."""

        return self._now


@pytest.fixture
def stub_launch_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch session manager browser launch to avoid spawning Playwright."""

    counter = 0

    async def _fake_launch(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str] | None = None,
    ) -> _MainStubHandle:
        nonlocal counter
        counter += 1
        return _MainStubHandle(f"ws://health/{counter}", pid=4500 + counter)

    monkeypatch.setattr("app.session_manager.launch_browser", _fake_launch)


@pytest.mark.anyio("asyncio")
async def test_health_endpoint_reports_extended_metrics(
    stub_launch_browser: None,
) -> None:
    """``GET /health`` should expose slots, proxy, VNC, and prewarm diagnostics."""

    clock = _ApiStubClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC))
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
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
    )

    await manager.create_session(SessionCreatePayload(headless=False))
    await manager.create_session(SessionCreatePayload(headless=False))
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
    ttl = payload["ttl"]
    assert ttl["reaper"] == {
        "total_runs": 0,
        "expired_sessions": 0,
        "last_run_at": None,
    }
    assert ttl["next_expiry_at"] == (
        clock() + timedelta(seconds=300)
    ).isoformat()


@pytest.mark.anyio("asyncio")
async def test_touch_endpoint_extends_idle_deadline(
    stub_launch_browser: None,
) -> None:
    """``POST /sessions/{id}/touch`` should refresh ``last_seen_at``."""

    clock = _ApiStubClock(datetime(2024, 2, 2, 10, 0, 0, tzinfo=UTC))
    settings = RunnerSettings(
        runner_id="runner-touch",
        camoufox_path="/usr/bin/camoufox",
    )
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
    )
    session = await manager.create_session(
        SessionCreatePayload(idle_ttl_seconds=45, headless=False)
    )

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            clock.advance(20)
            response = await client.post(f"/sessions/{session.id}/touch")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(session.id)
    expected_last_seen = clock().isoformat().replace("+00:00", "Z")
    assert body["last_seen_at"] == expected_last_seen
    metrics = await manager.get_metrics()
    assert metrics.next_idle_expiry_at == clock() + timedelta(seconds=45)
