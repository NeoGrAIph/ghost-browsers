"""Unit tests for FastAPI endpoints exposed by the runner application."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.config import RunnerSettings
from app.dependencies.session_manager import (
    get_event_publisher,
    get_runner_settings,
    get_session_manager,
)
from app.events import InMemorySessionEventPublisher
from app.main import app
from app.session_manager import SessionCreatePayload, SessionManager
from app.warm_pool import (
    WarmPoolReservation,
    WarmPoolSnapshot,
    WarmPoolState,
    WarmPoolStateError,
    WarmPoolStatistics,
)
from core.models import SessionVncDetails
from httpx import AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


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


class _MainStubBrowserHandle:
    """Minimal stub mirroring :class:`BrowserSessionHandle` for API tests."""

    def __init__(self, endpoint: str, pid: int) -> None:
        self.ws_endpoint = endpoint
        self.pid = pid
        self.shutdown_calls: list[dict[str, object]] = []

    async def shutdown(self, *, force: bool, timeout: float = 5.0) -> None:
        """Pretend to terminate the Playwright subprocess."""

        self.shutdown_calls.append({"force": force, "timeout": timeout})


class _MainStubWarmPool:
    """Warm pool stub exposing idle/reserved/busy transitions."""

    def __init__(self, *, workstations: list[str] | None = None) -> None:
        self._workstations = workstations or ["ws-1", "ws-2", "ws-3"]
        self._slots: dict[str, dict[str, object]] = {
            workstation: {
                "state": WarmPoolState.IDLE,
                "fingerprint": f"fp-{workstation}",
                "handle": _MainStubBrowserHandle(
                    f"ws://warm/{workstation}/0", pid=5000 + idx
                ),
            }
            for idx, workstation in enumerate(self._workstations)
        }
        self.reservations: list[str] = []
        self.busy: list[str] = []
        self.releases: list[str] = []
        self.draining = False

    async def start(self) -> None:
        """Warm pool stubs start instantly."""

        return None

    async def reserve_slot(self, workstation_id: str | None = None) -> WarmPoolReservation:
        """Reserve the first idle slot or a specific workstation."""

        if workstation_id is None:
            workstation_id = self._first_idle()
        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.IDLE:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not idle")
        slot["state"] = WarmPoolState.RESERVED
        self.reservations.append(workstation_id)
        snapshot = WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=None,
            state=WarmPoolState.RESERVED,
        )
        env = {
            "CAMOUFOX_WORKSTATION_ID": workstation_id,
            "CAMOUFOX_FINGERPRINT_ID": slot["fingerprint"],
        }
        handle = slot["handle"]
        assert isinstance(handle, _MainStubBrowserHandle)
        return WarmPoolReservation(snapshot=snapshot, handle=handle, environment=env)

    async def mark_busy(self, workstation_id: str) -> WarmPoolSnapshot:
        """Mark a reserved slot as busy."""

        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.RESERVED:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not reserved")
        slot["state"] = WarmPoolState.BUSY
        self.busy.append(workstation_id)
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=None,
            state=WarmPoolState.BUSY,
        )

    async def cancel_reservation(self, workstation_id: str) -> WarmPoolSnapshot:
        """Return a reserved slot to idle when session setup fails."""

        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.RESERVED:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not reserved")
        slot["state"] = WarmPoolState.IDLE
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=None,
            state=WarmPoolState.IDLE,
        )

    async def release_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Recycle a busy slot back to idle."""

        slot = self._require_slot(workstation_id)
        if slot["state"] not in {WarmPoolState.BUSY, WarmPoolState.RESERVED}:
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' cannot be recycled from {slot['state'].value}"
            )
        slot["state"] = WarmPoolState.IDLE
        self.releases.append(workstation_id)
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=None,
            state=WarmPoolState.IDLE,
        )

    def get_statistics(self) -> WarmPoolStatistics:
        """Return aggregate counts mirroring the real warm pool manager."""

        idle = sum(1 for slot in self._slots.values() if slot["state"] is WarmPoolState.IDLE)
        busy = sum(
            1
            for slot in self._slots.values()
            if slot["state"] in {WarmPoolState.RESERVED, WarmPoolState.BUSY}
        )
        error = sum(1 for slot in self._slots.values() if slot["state"] is WarmPoolState.ERROR)
        return WarmPoolStatistics(
            total=len(self._slots),
            idle=idle,
            busy=busy,
            error=error,
            draining=self.draining,
        )

    def _require_slot(self, workstation_id: str) -> dict[str, object]:
        try:
            return self._slots[workstation_id]
        except KeyError as exc:  # pragma: no cover - configuration guard
            raise WarmPoolStateError(f"unknown workstation '{workstation_id}'") from exc

    def _first_idle(self) -> str:
        for workstation_id, slot in self._slots.items():
            if slot["state"] is WarmPoolState.IDLE:
                return workstation_id
        raise WarmPoolStateError("no idle warm workstations available")


@pytest.mark.anyio("asyncio")
async def test_list_sessions_returns_empty_collection() -> None:
    """``GET /sessions`` should return an empty list when no sessions exist."""

    clock = _ApiStubClock(datetime(2024, 2, 1, 8, 0, 0, tzinfo=UTC))
    settings = RunnerSettings(runner_id="runner-list", camoufox_path="/usr/bin/camoufox")
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
        warm_pool_manager=_MainStubWarmPool(),
    )

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/sessions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio("asyncio")
async def test_list_sessions_returns_active_sessions() -> None:
    """``GET /sessions`` should mirror the sessions maintained in memory."""

    clock = _ApiStubClock(datetime(2024, 2, 1, 8, 30, 0, tzinfo=UTC))
    settings = RunnerSettings(runner_id="runner-list", camoufox_path="/usr/bin/camoufox")
    publisher = InMemorySessionEventPublisher()
    warm_pool = _MainStubWarmPool()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
        warm_pool_manager=warm_pool,
    )

    first = await manager.create_session(SessionCreatePayload(headless=False))
    second = await manager.create_session(SessionCreatePayload(headless=True))

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/sessions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {str(first.id), str(second.id)}

@pytest.mark.anyio("asyncio")
async def test_health_endpoint_reports_extended_metrics() -> None:
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
        prewarm_navigation=False,
    )
    publisher = InMemorySessionEventPublisher()
    warm_pool = _MainStubWarmPool()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
        warm_pool_manager=warm_pool,
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
    assert payload["warm_pool"] == {
        "enabled": True,
        "total": 3,
        "idle": 1,
        "busy": 2,
        "error": 0,
        "draining": False,
    }
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
        "enabled": False,
        "start_url": None,
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
async def test_metrics_endpoint_exposes_prometheus_payload() -> None:
    """``GET /metrics`` should serve Prometheus-formatted metrics."""

    clock = _ApiStubClock(datetime(2024, 3, 3, 12, 0, 0, tzinfo=UTC))
    settings = RunnerSettings(
        runner_id="runner-metrics",
        camoufox_path="/usr/bin/camoufox",
        vnc_enabled=True,
    )
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        reaper_interval_seconds=5.0,
        vnc_controller=_MainStubVncController(),
        warm_pool_manager=_MainStubWarmPool(),
    )

    await manager.create_session(SessionCreatePayload(headless=False))

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/metrics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "runner_active_sessions" in body
    assert "runner_vnc_allocations" in body
    assert "runner_vnc_allocation_requests_total" in body
    assert "runner_workstations_total" in body
    assert "runner_session_allocate_seconds_count" in body
    assert "runner_workstation_recycle_seconds_bucket" in body
    assert "runner_workstation_proxy_errors_total" in body
    assert "runner_workstation_navigation_errors_total" in body


@pytest.mark.anyio("asyncio")
async def test_touch_endpoint_extends_idle_deadline() -> None:
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
        warm_pool_manager=_MainStubWarmPool(),
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


@pytest.mark.anyio("asyncio")
async def test_create_session_returns_429_when_capacity_exhausted() -> None:
    """API should respond with 429 when the warm pool has no idle slots."""

    settings = RunnerSettings(runner_id="runner-cap", camoufox_path="/usr/bin/camoufox")
    publisher = InMemorySessionEventPublisher()
    warm_pool = _MainStubWarmPool(workstations=["ws-exhausted"])
    await warm_pool.reserve_slot("ws-exhausted")
    await warm_pool.mark_busy("ws-exhausted")
    manager = SessionManager(
        settings,
        publisher,
        vnc_controller=_MainStubVncController(),
        warm_pool_manager=warm_pool,
    )

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/sessions", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json()["detail"] == "no warm workstations available"
