"""Integration tests covering the warm workstation management API."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from app.browser import BrowserLaunchError
from app.config import RunnerSettings, WarmPoolConfig, WorkstationConfigEntry
from app.dependencies.session_manager import (
    get_warm_pool_manager,
    get_workstation_event_publisher,
)
from app.events import InMemoryWorkstationEventPublisher
from app.main import app
from app.warm_pool import WarmPoolManager, WarmPoolState
from core.models import WorkstationEventType, WorkstationState
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    """Force pytest-anyio to use asyncio for FastAPI integration tests."""

    return "asyncio"


class _StubHandle:
    """Minimal browser handle used by the warm pool during tests."""

    def __init__(self, workstation_id: str) -> None:
        self.workstation_id = workstation_id
        self.shutdown_calls: list[dict[str, object]] = []

    async def shutdown(self, *, force: bool, timeout: float = 5.0) -> None:
        """Record shutdown invocations for assertions."""

        self.shutdown_calls.append({"force": force, "timeout": timeout})


async def _build_warm_pool(
    tmp_path: Path,
    *,
    workstations: list[str],
    fail_next_launch: bool = False,
) -> tuple[
    WarmPoolManager,
    InMemoryWorkstationEventPublisher,
    list[_StubHandle],
    list[dict[str, str]],
]:
    """Construct a warm pool manager wired with deterministic dependencies."""

    publisher = InMemoryWorkstationEventPublisher()
    settings = RunnerSettings()
    config = WarmPoolConfig(
        workstations=[WorkstationConfigEntry(id=identifier) for identifier in workstations]
    )
    handles: list[_StubHandle] = []
    launch_env_history: list[dict[str, str]] = []
    failure_counter = {"remaining": 0}

    async def launcher(
        runner_settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
        browser_flags: dict[str, str] | None = None,
    ) -> _StubHandle:
        """Return synthetic handles while optionally simulating launch failures."""

        del runner_settings, browser, headless
        if failure_counter["remaining"]:
            failure_counter["remaining"] -= 1
            raise BrowserLaunchError("synthetic launch failure")
        launch_env_history.append(dict(env))
        if browser_flags:
            launch_env_history[-1].update(browser_flags)
        handle = _StubHandle(env["CAMOUFOX_WORKSTATION_ID"])
        handles.append(handle)
        return handle

    counters: defaultdict[str, int] = defaultdict(int)

    def temp_dir_factory(workstation_id: str) -> Path:
        """Allocate unique temporary directories per workstation."""

        index = counters[workstation_id]
        counters[workstation_id] += 1
        path = tmp_path / f"warm-{workstation_id}-{index}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=launcher,  # type: ignore[arg-type]
        temp_dir_factory=temp_dir_factory,
        event_publisher=publisher,
    )
    await manager.start()
    await publisher.drain()
    if fail_next_launch:
        failure_counter["remaining"] = 3
    return manager, publisher, handles, launch_env_history


async def _override_dependencies(
    manager: WarmPoolManager, publisher: InMemoryWorkstationEventPublisher
) -> None:
    """Override FastAPI dependencies for the duration of a test."""

    get_warm_pool_manager.cache_clear()
    get_workstation_event_publisher.cache_clear()
    app.dependency_overrides[get_warm_pool_manager] = lambda: manager
    app.dependency_overrides[get_workstation_event_publisher] = lambda: publisher


def _reset_overrides() -> None:
    """Clear dependency overrides applied during a test run."""

    app.dependency_overrides.clear()


@pytest.mark.anyio("asyncio")
async def test_list_workstations_returns_snapshot(tmp_path: Path) -> None:
    """``GET /workstations`` should expose configured warm pool slots."""

    manager, publisher, _, _ = await _build_warm_pool(tmp_path, workstations=["ws-a", "ws-b"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/workstations")
    finally:
        await manager.drain()
        _reset_overrides()

    body = response.json()
    assert response.status_code == 200
    assert body["items"][0]["workstation_id"] == "ws-a"
    assert body["items"][0]["state"] == WarmPoolState.IDLE.value


@pytest.mark.anyio("asyncio")
async def test_reserve_workstation_emits_state_change(tmp_path: Path) -> None:
    """Reserving a workstation should emit a state change event with launch env."""

    manager, publisher, _, env_history = await _build_warm_pool(
        tmp_path, workstations=["ws-alpha"]
    )
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/workstations/reserve",
                json={"workstation_id": "ws-alpha"},
            )
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"]["state"] == WarmPoolState.RESERVED.value
    assert events and events[0].type is WorkstationEventType.STATE_CHANGED
    assert events[0].reason == "reserved"
    assert events[0].workstation.state is WorkstationState.PROVISIONING
    assert events[0].workstation.metadata["launch_env"]["CAMOUFOX_WORKSTATION_ID"] == "ws-alpha"
    assert env_history and env_history[0]["CAMOUFOX_WORKSTATION_ID"] == "ws-alpha"


@pytest.mark.anyio("asyncio")
async def test_mark_busy_emits_state_event(tmp_path: Path) -> None:
    """Transition into BUSY should emit a workstation.state_changed event."""

    manager, publisher, _, _ = await _build_warm_pool(tmp_path, workstations=["ws-1"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.post("/workstations/reserve", json={"workstation_id": "ws-1"})
            await publisher.drain()
            response = await client.post("/workstations/ws-1/busy")
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 200
    assert events[0].type is WorkstationEventType.STATE_CHANGED
    assert events[0].reason == "busy"
    assert events[0].workstation.state is WorkstationState.ASSIGNED


@pytest.mark.anyio("asyncio")
async def test_cancel_reservation_emits_state_event(tmp_path: Path) -> None:
    """Cancelling a reservation should emit a workstation.state_changed event."""

    manager, publisher, _, _ = await _build_warm_pool(tmp_path, workstations=["ws-2"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.post("/workstations/reserve", json={"workstation_id": "ws-2"})
            await publisher.drain()
            response = await client.post("/workstations/ws-2/cancel")
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 200
    assert events[0].type is WorkstationEventType.STATE_CHANGED
    assert events[0].reason == "reservation-cancelled"
    assert events[0].workstation.state is WorkstationState.AVAILABLE


@pytest.mark.anyio("asyncio")
async def test_release_workstation_emits_recycled_event(tmp_path: Path) -> None:
    """Releasing a workstation should emit state change and recycled events."""

    manager, publisher, handles, _ = await _build_warm_pool(tmp_path, workstations=["ws-r"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.post("/workstations/reserve", json={"workstation_id": "ws-r"})
            await client.post("/workstations/ws-r/busy")
            await publisher.drain()
            response = await client.post("/workstations/ws-r/release")
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 200
    event_types = [event.type for event in events]
    assert WorkstationEventType.STATE_CHANGED in event_types
    assert WorkstationEventType.RECYCLED in event_types
    assert any(
        event.reason == "recycling"
        for event in events
        if event.type is WorkstationEventType.STATE_CHANGED
    )
    recycled_event = next(
        event for event in events if event.type is WorkstationEventType.RECYCLED
    )
    assert recycled_event.reason == "released"
    assert recycled_event.workstation.state is WorkstationState.AVAILABLE
    assert handles and handles[0].shutdown_calls, "Handle should have been recycled"


@pytest.mark.anyio("asyncio")
async def test_restart_endpoint_recycles_slot(tmp_path: Path) -> None:
    """Restart should recycle the workstation and emit recycle events."""

    manager, publisher, _, _ = await _build_warm_pool(tmp_path, workstations=["ws-restart"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await publisher.drain()
            response = await client.post("/workstations/ws-restart/restart")
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 200
    event_types = [event.type for event in events]
    assert WorkstationEventType.STATE_CHANGED in event_types
    assert WorkstationEventType.RECYCLED in event_types
    assert any(
        event.reason == "restart"
        for event in events
        if event.type is WorkstationEventType.STATE_CHANGED
    )
    recycled_event = next(
        event for event in events if event.type is WorkstationEventType.RECYCLED
    )
    assert recycled_event.reason == "restarted"


@pytest.mark.anyio("asyncio")
async def test_drain_and_enable_cycle(tmp_path: Path) -> None:
    """Drain and enable endpoints should toggle availability and emit events."""

    manager, publisher, _, _ = await _build_warm_pool(tmp_path, workstations=["ws-cycle"])
    await _override_dependencies(manager, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            drain_response = await client.post("/workstations/ws-cycle/drain")
            drain_events = await publisher.drain()
            enable_response = await client.post("/workstations/ws-cycle/enable")
    finally:
        await manager.drain()
        _reset_overrides()

    enable_events = await publisher.drain()
    assert drain_response.status_code == 200
    assert drain_events[0].type is WorkstationEventType.STATE_CHANGED
    assert drain_events[0].reason == "drain-slot"
    assert drain_events[0].workstation.state is WorkstationState.UNAVAILABLE

    assert enable_response.status_code == 200
    enable_types = [event.type for event in enable_events]
    assert WorkstationEventType.STATE_CHANGED in enable_types
    assert WorkstationEventType.RECYCLED in enable_types
    assert any(
        event.reason == "enable"
        for event in enable_events
        if event.type is WorkstationEventType.STATE_CHANGED
    )
    recycled_event = next(
        event for event in enable_events
        if event.type is WorkstationEventType.RECYCLED
    )
    assert recycled_event.reason == "enabled"
    assert recycled_event.workstation.state is WorkstationState.AVAILABLE


@pytest.mark.anyio("asyncio")
async def test_restart_failure_emits_error_event(tmp_path: Path) -> None:
    """Failed restarts should surface ``workstation.error`` events."""

    manager, publisher, _, _ = await _build_warm_pool(
        tmp_path, workstations=["ws-fail"], fail_next_launch=True
    )
    await _override_dependencies(manager, publisher)

    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await publisher.drain()
            response = await client.post("/workstations/ws-fail/restart")
    finally:
        await manager.drain()
        _reset_overrides()

    events = await publisher.drain()
    assert response.status_code == 500
    assert any(event.type is WorkstationEventType.ERROR for event in events)
    error_event = next(event for event in events if event.type is WorkstationEventType.ERROR)
    assert error_event.reason == "restart-failed"
    assert error_event.workstation.state is WorkstationState.UNAVAILABLE
