"""Unit tests for :mod:`app.warm_pool`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.browser import BrowserLaunchError
from app.config import RunnerSettings, WarmPoolConfig, WorkstationConfigEntry
from app.warm_pool import WarmPoolManager, WarmPoolSnapshot, WarmPoolState, WarmPoolStateError
from app.workstation_events import InMemoryWorkstationEventPublisher
from core import WorkstationEventType, WorkstationState


class _StubHandle:
    """Test double mimicking :class:`BrowserSessionHandle`."""

    def __init__(self, identifier: int) -> None:
        self.identifier = identifier
        self.ws_endpoint = f"ws://warm/{identifier}"
        self.shutdown_calls: list[dict[str, Any]] = []

    async def shutdown(self, *, force: bool = False, timeout: float = 5.0) -> None:
        """Record shutdown invocations for assertions."""

        self.shutdown_calls.append({"force": force, "timeout": timeout})


@pytest.fixture
def anyio_backend() -> str:
    """Use the asyncio backend for AnyIO-powered tests."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_start_provisions_slots_with_env_and_prewarm(tmp_path: Path) -> None:
    """The manager should provision slots, set env vars, and prewarm."""

    prefs_base = tmp_path / "prefs"
    prefs_base.mkdir()
    settings = RunnerSettings(
        runner_id="runner-test",
        camoufox_path="/usr/bin/camoufox",
        browser_prefs_path=prefs_base,
        prewarm_navigation=True,
        start_url="https://example.test",
        start_url_wait_ms=1500,
    )
    config = WarmPoolConfig(
        workstations=[
            WorkstationConfigEntry(
                id="ws-1",
                fingerprint_id="fp-1",
                proxy_url="http://proxy.local:3128",
                prefs_rel_path="profile.json",
            )
        ]
    )

    launch_calls: list[dict[str, Any]] = []
    nav_calls: list[tuple[WarmPoolSnapshot, _StubHandle, str]] = []
    sleep_calls: list[float] = []

    async def launcher(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
    ) -> _StubHandle:
        handle = _StubHandle(len(launch_calls))
        launch_calls.append({
            "settings": settings,
            "browser": browser,
            "headless": headless,
            "env": dict(env),
            "handle": handle,
        })
        return handle

    async def navigator(
        snapshot: WarmPoolSnapshot,
        handle: _StubHandle,
        start_url: str,
    ) -> None:
        nav_calls.append((snapshot, handle, start_url))

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    def temp_dir_factory(workstation_id: str) -> Path:
        path = tmp_path / f"warm-{workstation_id}-{len(launch_calls)}"
        path.mkdir()
        return path

    publisher = InMemoryWorkstationEventPublisher()
    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=launcher,
        navigator=navigator,
        sleep=sleep,
        temp_dir_factory=temp_dir_factory,
        workstation_event_publisher=publisher,
    )

    await manager.start()

    created_events = await publisher.drain()
    assert len(created_events) == 1
    created = created_events[0]
    assert created.type is WorkstationEventType.CREATED
    assert created.workstation.state is WorkstationState.AVAILABLE
    assert created.reason == "provisioned"

    slots = manager.list_slots()
    assert len(slots) == 1
    assert slots[0].state is WarmPoolState.IDLE
    assert slots[0].fingerprint_id == "fp-1"

    assert len(launch_calls) == 1
    env = launch_calls[0]["env"]
    assert env["CAMOUFOX_HEADLESS"] == "virtual"
    assert env["CAMOUFOX_FINGERPRINT_ID"] == "fp-1"
    assert env["CAMOUFOX_PROXY_URL"] == "http://proxy.local:3128"
    assert env["CAMOUFOX_PREFS_REL_PATH"] == "profile.json"
    assert env["CAMOUFOX_PREFS_BASE_PATH"] == str(prefs_base)
    assert env["CAMOUFOX_PROFILE_DIR"].startswith(str(tmp_path))

    assert len(nav_calls) == 1
    assert nav_calls[0][2] == str(settings.start_url)
    assert sleep_calls == [1.5]

    reservation = await manager.reserve_slot()
    assert reservation.snapshot.state is WarmPoolState.RESERVED
    assert reservation.environment["CAMOUFOX_WORKSTATION_ID"] == "ws-1"

    reserved_events = await publisher.drain()
    assert len(reserved_events) == 1
    reserved = reserved_events[0]
    assert reserved.reason == "reserved"
    assert reserved.workstation.state is WorkstationState.ASSIGNED


@pytest.mark.anyio("asyncio")
async def test_cancel_reservation_returns_slot_to_idle(tmp_path: Path) -> None:
    """Cancelling a reservation should return the workstation to idle."""

    settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
    config = WarmPoolConfig(workstations=[WorkstationConfigEntry(id="ws-1")])

    async def launcher(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
    ) -> _StubHandle:
        del settings, browser, headless
        handle = _StubHandle(0)
        handle.launch_env = dict(env)
        return handle

    publisher = InMemoryWorkstationEventPublisher()
    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=launcher,  # type: ignore[arg-type]
        workstation_event_publisher=publisher,
    )

    await manager.start()
    await publisher.drain()
    reservation = await manager.reserve_slot("ws-1")
    assert reservation.snapshot.state is WarmPoolState.RESERVED
    await publisher.drain()
    snapshot = await manager.cancel_reservation("ws-1")
    assert snapshot.state is WarmPoolState.IDLE
    cancel_events = await publisher.drain()
    assert cancel_events[-1].reason == "reservation cancelled"
    assert cancel_events[-1].workstation.state is WorkstationState.AVAILABLE
    follow_up = await manager.reserve_slot("ws-1")
    assert follow_up.snapshot.state is WarmPoolState.RESERVED
    await publisher.drain()


@pytest.mark.anyio("asyncio")
async def test_launch_failures_trigger_retries(tmp_path: Path) -> None:
    """Launch errors should trigger exponential backoff and set error state."""

    settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
    config = WarmPoolConfig(workstations=[WorkstationConfigEntry(id="ws-err")])

    attempts = 0
    sleep_calls: list[float] = []

    async def failing_launcher(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
    ) -> _StubHandle:
        nonlocal attempts
        attempts += 1
        raise BrowserLaunchError("boom")

    async def sleep(delay: float) -> None:
        sleep_calls.append(delay)

    publisher = InMemoryWorkstationEventPublisher()
    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=failing_launcher,  # type: ignore[arg-type]
        sleep=sleep,
        max_retries=3,
        retry_base_delay=0.1,
        workstation_event_publisher=publisher,
    )

    await manager.start()
    failure_events = await publisher.drain()
    assert failure_events
    failed = failure_events[0]
    assert failed.type is WorkstationEventType.UPDATED
    assert failed.workstation.state is WorkstationState.UNAVAILABLE
    assert failed.reason == "boom"

    slots = manager.list_slots()
    assert slots[0].state is WarmPoolState.ERROR
    assert attempts == 3
    assert sleep_calls == [0.1, 0.2]

    with pytest.raises(WarmPoolStateError):
        await manager.reserve_slot("ws-err")


@pytest.mark.anyio("asyncio")
async def test_recycle_relaunches_with_same_fingerprint(tmp_path: Path) -> None:
    """Recycling should shutdown the old browser, cleanup, and relaunch."""

    settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
    config = WarmPoolConfig(
        workstations=[
            WorkstationConfigEntry(
                id="ws-1",
                fingerprint_id="fp-keep",
                proxy_url="http://proxy:3128",
            )
        ]
    )

    handles: list[_StubHandle] = []
    env_history: list[dict[str, str]] = []

    async def launcher(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
    ) -> _StubHandle:
        handle = _StubHandle(len(handles))
        handles.append(handle)
        env_history.append(dict(env))
        return handle

    temp_roots: list[Path] = []

    def temp_dir_factory(workstation_id: str) -> Path:
        path = tmp_path / f"{workstation_id}-{len(temp_roots)}"
        path.mkdir()
        temp_roots.append(path)
        return path

    publisher = InMemoryWorkstationEventPublisher()
    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=launcher,  # type: ignore[arg-type]
        temp_dir_factory=temp_dir_factory,
        workstation_event_publisher=publisher,
    )

    await manager.start()
    await publisher.drain()
    assert handles

    await manager.reserve_slot("ws-1")
    await publisher.drain()
    await manager.mark_busy("ws-1")
    await publisher.drain()
    recycled = await manager.release_slot("ws-1")

    assert recycled.state is WarmPoolState.IDLE
    assert len(handles) == 2
    assert handles[0].shutdown_calls[-1]["force"] is True
    assert env_history[0]["CAMOUFOX_FINGERPRINT_ID"] == "fp-keep"
    assert env_history[1]["CAMOUFOX_FINGERPRINT_ID"] == "fp-keep"
    assert not temp_roots[0].exists()
    assert temp_roots[1].exists()

    recycle_events = await publisher.drain()
    assert [event.reason for event in recycle_events] == ["recycling", "recycled"]
    assert recycle_events[0].workstation.state is WorkstationState.PROVISIONING
    assert recycle_events[1].workstation.state is WorkstationState.AVAILABLE


@pytest.mark.anyio("asyncio")
async def test_drain_transitions_slots_and_prevents_reservations(tmp_path: Path) -> None:
    """Draining should tear down browsers and block future reservations."""

    settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
    config = WarmPoolConfig(
        workstations=[
            WorkstationConfigEntry(id="ws-1"),
            WorkstationConfigEntry(id="ws-2"),
        ]
    )

    handles: list[_StubHandle] = []

    async def launcher(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str],
    ) -> _StubHandle:
        handle = _StubHandle(len(handles))
        handles.append(handle)
        return handle

    publisher = InMemoryWorkstationEventPublisher()
    manager = WarmPoolManager(
        settings,
        warm_pool_config=config,
        launcher=launcher,  # type: ignore[arg-type]
        workstation_event_publisher=publisher,
    )

    await manager.start()
    await publisher.drain()
    drain_snapshots = await manager.drain()

    assert all(snapshot.state is WarmPoolState.DRAINING for snapshot in drain_snapshots)
    for handle in handles:
        assert handle.shutdown_calls and handle.shutdown_calls[-1]["force"] is True

    with pytest.raises(WarmPoolStateError):
        await manager.reserve_slot()

    drain_events = await publisher.drain()
    assert all(event.type is WorkstationEventType.RELEASED for event in drain_events)
    assert {event.workstation.id for event in drain_events} == {"ws-1", "ws-2"}
    assert all(event.workstation.state is WorkstationState.UNAVAILABLE for event in drain_events)

