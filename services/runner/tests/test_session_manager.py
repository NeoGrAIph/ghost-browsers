"""Unit tests for :mod:`app.session_manager`."""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID

import pytest
from app.config import RunnerSettings, WarmPoolMode
from app.events import InMemorySessionEventPublisher
from app.metrics import METRICS_REGISTRY
from app.session_manager import (
    SessionCapacityError,
    SessionCreatePayload,
    SessionManager,
    SessionUpdatePayload,
)
from app.vnc import VncSessionHandle
from app.warm_pool import (
    WarmPoolReservation,
    WarmPoolSnapshot,
    WarmPoolState,
    WarmPoolStateError,
    WarmPoolStatistics,
)
from core.models import (
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
)


class _StubBrowserHandle:
    """Test double mimicking :class:`BrowserSessionHandle`."""

    def __init__(self, *, ws_endpoint: str, pid: int) -> None:
        self.ws_endpoint = ws_endpoint
        self.pid = pid
        self.shutdown_calls: list[dict[str, object]] = []
        self.launch_env: dict[str, str] = {}

    async def shutdown(self, *, force: bool, timeout: float = 5.0) -> None:
        """Record shutdown invocations for assertions."""

        self.shutdown_calls.append({"force": force, "timeout": timeout})


class _StubWarmPoolManager:
    """In-memory warm pool stub returning deterministic handles."""

    def __init__(self, *, workstations: list[str] | None = None) -> None:
        self._workstations = workstations or ["ws-1", "ws-2", "ws-3"]
        self._slots: dict[str, dict[str, object]] = {}
        self._counter = 0
        self.started = False
        self.reservations: list[str] = []
        self.cancellations: list[str] = []
        self.busy: list[str] = []
        self.releases: list[str] = []
        for workstation in self._workstations:
            self._slots[workstation] = {
                "state": WarmPoolState.IDLE,
                "fingerprint": f"fp-{workstation}",
                "proxy": None,
                "handle": self._make_handle(workstation),
            }

    async def start(self) -> None:
        """Mark the stub as initialised."""

        self.started = True

    async def reserve_slot(self, workstation_id: str | None = None) -> WarmPoolReservation:
        """Transition an idle slot into the reserved state."""

        if workstation_id is None:
            workstation_id = self._first_idle()
        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.IDLE:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not idle")
        slot["state"] = WarmPoolState.RESERVED
        snapshot = WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=slot["proxy"],
            state=WarmPoolState.RESERVED,
        )
        env = {
            "CAMOUFOX_WORKSTATION_ID": workstation_id,
            "CAMOUFOX_FINGERPRINT_ID": slot["fingerprint"],
        }
        handle = slot["handle"]
        assert isinstance(handle, _StubBrowserHandle)
        handle.launch_env = dict(env)
        self.reservations.append(workstation_id)
        return WarmPoolReservation(snapshot=snapshot, handle=handle, environment=env)

    async def mark_busy(self, workstation_id: str) -> WarmPoolSnapshot:
        """Record that a reserved slot is now busy."""

        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.RESERVED:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not reserved")
        slot["state"] = WarmPoolState.BUSY
        self.busy.append(workstation_id)
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=slot["proxy"],
            state=WarmPoolState.BUSY,
        )

    async def cancel_reservation(self, workstation_id: str) -> WarmPoolSnapshot:
        """Return a reserved slot to the idle state without recycling."""

        slot = self._require_slot(workstation_id)
        if slot["state"] is not WarmPoolState.RESERVED:
            raise WarmPoolStateError(f"workstation '{workstation_id}' is not reserved")
        slot["state"] = WarmPoolState.IDLE
        self.cancellations.append(workstation_id)
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=slot["proxy"],
            state=WarmPoolState.IDLE,
        )

    async def release_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Recycle a busy slot back into the idle pool."""

        slot = self._require_slot(workstation_id)
        if slot["state"] not in {WarmPoolState.BUSY, WarmPoolState.RESERVED}:
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' cannot be recycled from {slot['state'].value}"
            )
        slot["state"] = WarmPoolState.RECYCLING
        handle = slot["handle"]
        assert isinstance(handle, _StubBrowserHandle)
        await handle.shutdown(force=True)
        slot["handle"] = self._make_handle(workstation_id)
        slot["state"] = WarmPoolState.IDLE
        self.releases.append(workstation_id)
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=slot["fingerprint"],
            proxy_url=slot["proxy"],
            state=WarmPoolState.IDLE,
        )

    def get_statistics(self) -> WarmPoolStatistics:
        """Return utilisation counters for compatibility with the real manager."""

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
            draining=False,
        )

    def _make_handle(self, workstation_id: str) -> _StubBrowserHandle:
        handle = _StubBrowserHandle(
            ws_endpoint=f"ws://warm/{workstation_id}/{self._counter}",
            pid=4400 + self._counter,
        )
        self._counter += 1
        return handle

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


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


def _build_manager(
    settings: RunnerSettings,
    publisher: InMemorySessionEventPublisher,
    *,
    clock: Callable[[], datetime] | None = None,
    vnc_controller: "_StubVncController" | None = None,
    warm_pool: _StubWarmPoolManager | None = None,
    use_warm_pool: bool = True,
) -> tuple[SessionManager, _StubWarmPoolManager | None]:
    """Instantiate a session manager with optional warm pool support."""

    warm_pool_manager = warm_pool
    if warm_pool_manager is None and use_warm_pool:
        warm_pool_manager = _StubWarmPoolManager()
    manager = SessionManager(
        settings,
        publisher,
        clock=clock,
        vnc_controller=vnc_controller,
        warm_pool_manager=warm_pool_manager,
    )
    return manager, warm_pool_manager


@pytest.fixture
def stub_vnc_controller() -> _StubVncController:
    """Provide a fake VNC controller for tests that expect noVNC support."""

    return _StubVncController()


@pytest.mark.anyio("asyncio")
async def test_create_session_emits_event_and_vnc_stub(
    stub_vnc_controller: _StubVncController,
) -> None:
    """``create_session`` should store the session and publish a CREATED event."""

    clock_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    settings = RunnerSettings(
        runner_id="runner-test",
        camoufox_path="/usr/bin/camoufox",
        vnc_http_base_url="http://localhost:9000/vnc",
        vnc_ws_base_url="ws://localhost:9000/vnc",
        vnc_token_ttl_seconds=60,
    )
    publisher = InMemorySessionEventPublisher()
    manager, warm_pool = _build_manager(
        settings,
        publisher,
        clock=lambda: clock_now,
        vnc_controller=stub_vnc_controller,
    )

    payload = SessionCreatePayload(
        start_url="https://example.test",
        headless=False,
        proxy=SessionProxySettings(http="http://proxy.example:3128"),
        metadata={"flow": "smoke"},
    )

    session = await manager.create_session(payload)
    assert warm_pool is not None

    assert session.runner_id == "runner-test"
    assert session.proxy is not None
    assert session.vnc is not None
    assert session.vnc.token is None
    assert session.vnc.token_ttl_seconds is None
    assert str(session.vnc.http_url).startswith("http://stub-vnc/")
    warm_meta = session.metadata.get("warm_pool", {})
    assert warm_meta["workstation_id"] == warm_pool.reservations[0]
    assert warm_meta["fingerprint_id"].startswith("fp-")
    origin = session.metadata["browser_origin"]
    assert origin["kind"] == "warm_pool"
    assert origin["mode"] == settings.warm_pool_mode.value
    assert origin["workstation_id"] == warm_pool.reservations[0]
    events = await publisher.drain()
    assert len(events) == 1
    assert events[0].type is SessionEventType.CREATED
    assert events[0].session.id == session.id
    assert events[0].occurred_at == clock_now


@pytest.mark.anyio("asyncio")
async def test_create_session_headless_disables_vnc_flag(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Headless sessions must not persist VNC handles or enable the flag."""

    settings = RunnerSettings(
        runner_id="runner-headless",
        camoufox_path="/usr/bin/camoufox",
    )
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
    )

    session = await manager.create_session(
        SessionCreatePayload(headless=True, vnc_enabled=True)
    )

    assert session.headless is True
    assert session.vnc is None
    assert session.vnc_enabled is False
    assert session.id not in manager._vnc_handles


@pytest.mark.anyio("asyncio")
async def test_create_session_disables_vnc_when_allocation_fails(
    monkeypatch: pytest.MonkeyPatch, stub_vnc_controller: _StubVncController
) -> None:
    """Failed VNC allocations should force ``vnc_enabled`` to ``False``."""

    settings = RunnerSettings(
        runner_id="runner-vnc-fail",
        camoufox_path="/usr/bin/camoufox",
    )
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
    )

    async def _fail_resolve(
        self: SessionManager,
        payload: SessionCreatePayload,
        session_id: UUID,
        *,
        sanitized_vnc: SessionVncDetails | None,
    ) -> tuple[SessionVncDetails | None, VncSessionHandle | None]:
        del payload, session_id, sanitized_vnc
        return None, None

    monkeypatch.setattr(
        manager,
        "_resolve_vnc",
        types.MethodType(_fail_resolve, manager),
    )

    session = await manager.create_session(
        SessionCreatePayload(headless=False, vnc_enabled=True)
    )

    assert session.vnc is None
    assert session.vnc_enabled is False
    assert session.id not in manager._vnc_handles


@pytest.mark.anyio("asyncio")
async def test_create_session_raises_when_warm_pool_exhausted(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Pool exhaustion should surface as a capacity error."""

    publisher = InMemorySessionEventPublisher()
    warm_pool = _StubWarmPoolManager(workstations=["ws-only"])
    await warm_pool.reserve_slot("ws-only")
    await warm_pool.mark_busy("ws-only")
    settings = RunnerSettings(
        runner_id="runner-capacity",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.WARM_ONLY,
    )
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
        warm_pool=warm_pool,
    )

    with pytest.raises(SessionCapacityError):
        await manager.create_session(SessionCreatePayload())


@pytest.mark.anyio("asyncio")
async def test_create_session_cold_only_launches_new_browser(
    monkeypatch: pytest.MonkeyPatch, stub_vnc_controller: _StubVncController
) -> None:
    """Cold-only mode should bypass the warm pool and spawn a fresh browser."""

    calls: list[dict[str, object]] = []

    async def _fake_launch(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
        read_timeout: float = 10.0,
        browser_flags: dict[str, str] | None = None,
    ) -> _StubBrowserHandle:
        handle = _StubBrowserHandle(ws_endpoint="ws://cold/0", pid=8800)
        calls.append(
            {
                "browser": browser,
                "headless": headless,
                "env": dict(env or {}),
                "timeout": read_timeout,
                "browser_flags": dict(browser_flags or {}),
            }
        )
        return handle

    monkeypatch.setattr("app.session_manager.launch_browser", _fake_launch)

    settings = RunnerSettings(
        runner_id="runner-cold",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.COLD_ONLY,
    )
    publisher = InMemorySessionEventPublisher()
    manager, warm_pool = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
        use_warm_pool=False,
    )

    session = await manager.create_session(SessionCreatePayload(headless=False))

    assert warm_pool is None
    assert calls
    launch_call = calls[0]
    assert launch_call["browser"] == "camoufox"
    assert launch_call["headless"] is False
    assert launch_call["env"] == {"DISPLAY": ":stub"}
    assert launch_call["browser_flags"] == {}
    origin = session.metadata["browser_origin"]
    assert origin["kind"] == "cold_launch"
    assert origin["mode"] == settings.warm_pool_mode.value
    assert origin["reason"] == "mode-cold-only"
    assert "warm_pool" not in session.metadata
    assert session.metadata["runner_browser_pid"] == 8800


@pytest.mark.anyio("asyncio")
async def test_cold_launch_merges_browser_flags_from_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold launches should union runner-level and request-specific flags."""

    calls: list[dict[str, object]] = []

    async def _fake_launch(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str] | None = None,
        browser_flags: dict[str, str] | None = None,
        read_timeout: float = 10.0,
        command: list[str] | None = None,
    ) -> _StubBrowserHandle:
        del settings, browser, headless, env, read_timeout, command
        handle = _StubBrowserHandle(ws_endpoint="ws://cold/flags", pid=7700)
        calls.append({"browser_flags": dict(browser_flags or {})})
        return handle

    monkeypatch.setattr("app.session_manager.launch_browser", _fake_launch)

    settings = RunnerSettings(
        runner_id="runner-flags",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.COLD_ONLY,
        browser_required_flags={"MOZ_DISABLE_HTTP3": "1"},
    )
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(settings, publisher, use_warm_pool=False)

    payload = SessionCreatePayload(
        headless=True,
        metadata={"browser_flags": {"EXTRA_FLAG": True}},
    )

    session = await manager.create_session(payload)

    assert calls
    launch_call = calls[0]
    assert launch_call["browser_flags"] == {
        "MOZ_DISABLE_HTTP3": "1",
        "EXTRA_FLAG": "1",
    }
    assert session.metadata["browser_flags"] == launch_call["browser_flags"]
    origin = session.metadata["browser_origin"]
    assert origin["kind"] == "cold_launch"
    assert origin["reason"] == "mode-cold-only"


@pytest.mark.anyio("asyncio")
async def test_create_session_hybrid_falls_back_when_warm_pool_busy(
    monkeypatch: pytest.MonkeyPatch, stub_vnc_controller: _StubVncController
) -> None:
    """Hybrid mode should fall back to cold launches when the pool is exhausted."""

    calls: list[dict[str, object]] = []

    async def _fake_launch(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
        read_timeout: float = 10.0,
        browser_flags: dict[str, str] | None = None,
    ) -> _StubBrowserHandle:
        handle = _StubBrowserHandle(ws_endpoint="ws://cold/fallback", pid=9900)
        calls.append(
            {
                "browser": browser,
                "headless": headless,
                "env": dict(env or {}),
                "timeout": read_timeout,
                "browser_flags": dict(browser_flags or {}),
            }
        )
        return handle

    monkeypatch.setattr("app.session_manager.launch_browser", _fake_launch)

    warm_pool = _StubWarmPoolManager(workstations=["ws-only"])
    await warm_pool.reserve_slot("ws-only")
    await warm_pool.mark_busy("ws-only")

    settings = RunnerSettings(
        runner_id="runner-hybrid",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.HYBRID,
    )
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
        warm_pool=warm_pool,
    )

    session = await manager.create_session(SessionCreatePayload(headless=False))

    assert calls
    launch_call = calls[0]
    assert launch_call["headless"] is False
    assert launch_call["env"] == {"DISPLAY": ":stub"}
    assert launch_call["browser_flags"] == {}
    origin = session.metadata["browser_origin"]
    assert origin["kind"] == "cold_launch"
    assert origin["mode"] == settings.warm_pool_mode.value
    assert origin["reason"] == "warm-pool-unavailable"
    assert "warm_pool" not in session.metadata
    assert session.metadata["runner_browser_pid"] == 9900


@pytest.mark.anyio("asyncio")
async def test_warm_only_rejects_custom_browser_flags(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Warm-only mode should reject sessions requiring bespoke browser flags."""

    publisher = InMemorySessionEventPublisher()
    warm_pool = _StubWarmPoolManager()
    settings = RunnerSettings(
        runner_id="runner-warm",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.WARM_ONLY,
    )
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
        warm_pool=warm_pool,
    )

    payload = SessionCreatePayload(metadata={"browser_flags": {"EXTRA": "flag"}})

    with pytest.raises(SessionCapacityError):
        await manager.create_session(payload)

    assert warm_pool.reservations == []


@pytest.mark.anyio("asyncio")
async def test_hybrid_skips_warm_pool_for_custom_browser_flags(
    monkeypatch: pytest.MonkeyPatch, stub_vnc_controller: _StubVncController
) -> None:
    """Hybrid mode should bypass warm slots when additional flags are requested."""

    calls: list[dict[str, object]] = []

    async def _fake_launch(
        settings: RunnerSettings,
        *,
        browser: str,
        headless: bool,
        env: dict[str, str] | None = None,
        browser_flags: dict[str, str] | None = None,
        read_timeout: float = 10.0,
        command: list[str] | None = None,
    ) -> _StubBrowserHandle:
        del settings, browser, headless, env, read_timeout, command
        handle = _StubBrowserHandle(ws_endpoint="ws://cold/custom", pid=8801)
        calls.append({"browser_flags": dict(browser_flags or {})})
        return handle

    monkeypatch.setattr("app.session_manager.launch_browser", _fake_launch)

    warm_pool = _StubWarmPoolManager()
    settings = RunnerSettings(
        runner_id="runner-hybrid-flags",
        camoufox_path="/usr/bin/camoufox",
        warm_pool_mode=WarmPoolMode.HYBRID,
    )
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        settings,
        publisher,
        vnc_controller=stub_vnc_controller,
        warm_pool=warm_pool,
    )

    payload = SessionCreatePayload(
        headless=True,
        metadata={"browser_flags": {"EXTRA": "flag"}},
    )

    session = await manager.create_session(payload)

    assert warm_pool.reservations == []
    assert calls
    launch_call = calls[0]
    assert launch_call["browser_flags"] == {"EXTRA": "flag"}
    metadata = session.metadata
    assert metadata["browser_flags"] == {"EXTRA": "flag"}
    origin = metadata["browser_origin"]
    assert origin["kind"] == "cold_launch"
    assert origin["reason"] == "custom-browser-flags"


@pytest.mark.anyio("asyncio")
async def test_update_session_merges_labels_and_publishes_update(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Updates should merge labels and emit ``session.updated`` events."""

    clock_now = datetime(2024, 2, 2, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(runner_id="runner-test", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=lambda: clock_now,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(SessionCreatePayload(headless=True))

    updated = await manager.update_session(
        session.id,
        SessionUpdatePayload(
            labels={"env": "test"},
            metadata={"step": 1},
            status=SessionStatus.READY,
        ),
    )

    assert updated.labels["env"] == "test"
    assert updated.metadata["step"] == 1
    events = await publisher.drain()
    assert [event.type for event in events] == [SessionEventType.CREATED, SessionEventType.UPDATED]
    assert events[-1].session.status is SessionStatus.READY
    assert events[-1].occurred_at == clock_now


@pytest.mark.anyio("asyncio")
async def test_create_session_strips_user_vnc_token(
    stub_vnc_controller: _StubVncController,
) -> None:
    """User-supplied VNC tokens must be removed before persisting sessions."""

    clock_now = datetime(2024, 4, 4, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(
            runner_id="runner-token", camoufox_path="/usr/bin/camoufox"
        ),
        publisher,
        clock=lambda: clock_now,
        vnc_controller=stub_vnc_controller,
    )
    payload = SessionCreatePayload(
        headless=False,
        vnc=SessionVncDetails(
            http_url="http://127.0.0.1:6901/view",
            token="forged",
            token_ttl_seconds=120,
        ),
    )

    session = await manager.create_session(payload)

    assert session.vnc is not None
    assert session.vnc.token is None
    assert session.vnc.token_ttl_seconds is None


@pytest.mark.anyio("asyncio")
async def test_update_session_strips_user_vnc_token(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Updates attempting to inject VNC tokens are sanitised."""

    clock_now = datetime(2024, 5, 5, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(
            runner_id="runner-update", camoufox_path="/usr/bin/camoufox"
        ),
        publisher,
        clock=lambda: clock_now,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(
        SessionCreatePayload(headless=False)
    )

    updated = await manager.update_session(
        session.id,
        SessionUpdatePayload(
            vnc=SessionVncDetails(
                http_url="http://127.0.0.1:6901/view",
                token="override",
                token_ttl_seconds=200,
            )
        ),
    )

    assert updated.vnc is not None
    assert updated.vnc.token is None
    assert updated.vnc.token_ttl_seconds is None


@pytest.mark.anyio("asyncio")
async def test_update_session_disables_vnc_when_details_removed(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Clearing VNC details must also disable the ``vnc_enabled`` flag."""

    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(
            runner_id="runner-update-vnc",
            camoufox_path="/usr/bin/camoufox",
        ),
        publisher,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(SessionCreatePayload(headless=False))
    assert session.vnc is not None
    assert session.vnc_enabled is True

    updated = await manager.update_session(
        session.id,
        SessionUpdatePayload(vnc=None, vnc_enabled=True),
    )

    assert updated.vnc is None
    assert updated.vnc_enabled is False
    assert session.id not in manager._vnc_handles


@pytest.mark.anyio("asyncio")
async def test_end_session_sets_terminal_state_and_event(
    stub_vnc_controller: _StubVncController,
) -> None:
    """``end_session`` should mark the session as DEAD and send ENDED event."""

    clock_now = datetime(2024, 3, 3, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager, warm_pool = _build_manager(
        RunnerSettings(runner_id="runner-test", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=lambda: clock_now,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(SessionCreatePayload())

    ended = await manager.end_session(session.id, reason="completed")

    assert ended.status is SessionStatus.DEAD
    assert ended.ended_at == clock_now
    assert warm_pool.releases == [session.metadata["warm_pool"]["workstation_id"]]
    events = await publisher.drain()
    assert [event.type for event in events] == [SessionEventType.CREATED, SessionEventType.ENDED]
    assert events[-1].reason == "completed"


@pytest.mark.anyio("asyncio")
async def test_metrics_track_active_sessions_and_prewarm_failures(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Metrics should reflect active sessions and retain bounded prewarm errors."""

    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(
            runner_id="runner-metrics",
            camoufox_path="/usr/bin/camoufox",
            slot_limit=3,
            prewarm_failure_history_size=2,
        ),
        publisher,
        vnc_controller=stub_vnc_controller,
    )

    await manager.create_session(SessionCreatePayload())
    await manager.create_session(SessionCreatePayload())
    await manager.record_prewarm_failure("warmup-1")
    await manager.record_prewarm_failure("warmup-2")
    metrics = await manager.get_metrics()

    assert metrics.active_sessions == 2
    assert metrics.prewarm_failure_count == 2
    assert metrics.prewarm_failures == ["warmup-1", "warmup-2"]


@pytest.mark.anyio("asyncio")
async def test_prometheus_metrics_follow_session_and_vnc_lifecycle(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Prometheus gauges should mirror active sessions and VNC allocations."""

    def _sample(name: str) -> float:
        value = METRICS_REGISTRY.get_sample_value(name)
        return 0.0 if value is None else value

    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(runner_id="runner-prom", camoufox_path="/usr/bin/camoufox"),
        publisher,
        vnc_controller=stub_vnc_controller,
    )

    post_init_active = _sample("runner_active_sessions")
    post_init_vnc = _sample("runner_vnc_allocations")

    session = await manager.create_session(SessionCreatePayload(headless=False))

    assert _sample("runner_active_sessions") == pytest.approx(post_init_active + 1.0)
    assert _sample("runner_vnc_allocations") == pytest.approx(post_init_vnc + 1.0)

    await manager.end_session(session.id)

    assert _sample("runner_active_sessions") == pytest.approx(post_init_active)
    assert _sample("runner_vnc_allocations") == pytest.approx(post_init_vnc)


@pytest.mark.anyio("asyncio")
async def test_touch_session_updates_last_seen_and_publishes_update(
    stub_vnc_controller: _StubVncController,
) -> None:
    """``touch_session`` should extend TTL and emit a heartbeat update."""

    clock = _StubClock(datetime(2024, 6, 6, 12, 0, 0, tzinfo=UTC))
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(runner_id="runner-touch", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=clock,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(
        SessionCreatePayload(idle_ttl_seconds=60)
    )

    clock.advance(15)
    touched = await manager.touch_session(session.id)

    assert touched.last_seen_at == clock()
    events = await publisher.drain()
    assert [event.type for event in events] == [
        SessionEventType.CREATED,
        SessionEventType.UPDATED,
    ]
    assert events[-1].session.id == session.id


@pytest.mark.anyio("asyncio")
async def test_reap_expired_sessions_marks_session_dead_and_records_metrics(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Idle sessions should transition to DEAD with an ``idle-timeout`` reason."""

    clock = _StubClock(datetime(2024, 7, 7, 12, 0, 0, tzinfo=UTC))
    publisher = InMemorySessionEventPublisher()
    manager, warm_pool = _build_manager(
        RunnerSettings(runner_id="runner-reap", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=clock,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(
        SessionCreatePayload(idle_ttl_seconds=30)
    )

    runs_before = METRICS_REGISTRY.get_sample_value("runner_reaper_runs_total") or 0.0
    expired_before = (
        METRICS_REGISTRY.get_sample_value("runner_reaper_expired_sessions_total")
        or 0.0
    )

    clock.advance(31)
    expired = await manager.reap_expired_sessions()

    assert expired == 1
    ended = await manager.get_session(session.id)
    assert ended.status is SessionStatus.DEAD
    events = await publisher.drain()
    assert [event.type for event in events] == [
        SessionEventType.CREATED,
        SessionEventType.ENDED,
    ]
    assert events[-1].reason == "idle-timeout"
    metrics = await manager.get_metrics()
    assert metrics.reaper_expired_sessions == 1
    assert warm_pool.releases == [session.metadata["warm_pool"]["workstation_id"]]
    assert metrics.reaper_total_runs == 1
    assert metrics.next_idle_expiry_at is None
    assert (
        METRICS_REGISTRY.get_sample_value("runner_reaper_runs_total")
        == pytest.approx(runs_before + 1.0)
    )
    assert (
        METRICS_REGISTRY.get_sample_value("runner_reaper_expired_sessions_total")
        == pytest.approx(expired_before + 1.0)
    )


@pytest.mark.anyio("asyncio")
async def test_reap_skips_recently_touched_session(
    stub_vnc_controller: _StubVncController,
) -> None:
    """Touching a session should postpone its idle deadline for reaper runs."""

    clock = _StubClock(datetime(2024, 8, 8, 12, 0, 0, tzinfo=UTC))
    publisher = InMemorySessionEventPublisher()
    manager, _ = _build_manager(
        RunnerSettings(runner_id="runner-skip", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=clock,
        vnc_controller=stub_vnc_controller,
    )
    session = await manager.create_session(
        SessionCreatePayload(idle_ttl_seconds=40)
    )

    clock.advance(20)
    assert await manager.reap_expired_sessions() == 0
    metrics = await manager.get_metrics()
    expected_expiry = session.last_seen_at + timedelta(seconds=40)
    assert metrics.next_idle_expiry_at == expected_expiry

    clock.advance(5)
    touched = await manager.touch_session(session.id)
    clock.advance(10)
    assert await manager.reap_expired_sessions() == 0
    metrics_after_touch = await manager.get_metrics()
    assert metrics_after_touch.reaper_total_runs == 2
    assert metrics_after_touch.reaper_expired_sessions == 0
    assert (
        metrics_after_touch.next_idle_expiry_at
        == touched.last_seen_at + timedelta(seconds=40)
    )
class _StubClock:
    """Mutable clock fixture to deterministically advance time in tests."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def advance(self, seconds: float) -> None:
        """Advance the current time by ``seconds`` in place."""

        self._now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        """Return the current timestamp."""

        return self._now


class _StubVncHandle:
    """Lightweight handle representing a fake VNC allocation."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.details = SessionVncDetails(
            http_url=f"http://stub-vnc/{session_id}",
            websocket_url=f"ws://stub-vnc/{session_id}",
            token=None,
            token_ttl_seconds=None,
        )
        self.browser_env = {"DISPLAY": ":stub"}
        self.released = False

    def browser_environment(self) -> dict[str, str]:
        """Expose environment variables expected by the runner."""

        return dict(self.browser_env)


class _StubVncController:
    """Test double implementing the VNC controller protocol."""

    def __init__(self) -> None:
        self.handles: dict[str, _StubVncHandle] = {}

    async def allocate(self, session_id: str) -> _StubVncHandle:
        """Return a predictable handle keyed by ``session_id``."""

        handle = _StubVncHandle(session_id)
        self.handles[session_id] = handle
        return handle

    async def release(self, handle: _StubVncHandle | None) -> None:
        """Mark the handle as released to assert cleanup paths."""

        if handle is None:
            return
        handle.released = True


@pytest.mark.anyio("asyncio")
async def test_create_session_uses_warm_pool_handle() -> None:
    """Sessions should reuse warm pool handles and enrich metadata."""

    publisher = InMemorySessionEventPublisher()
    warm_pool = _StubWarmPoolManager(workstations=["ws-meta"])
    settings = RunnerSettings(
        runner_id="runner-browser", camoufox_path="/usr/bin/camoufox"
    )
    manager, warm_pool = _build_manager(
        settings,
        publisher,
        warm_pool=warm_pool,
    )

    session = await manager.create_session(
        SessionCreatePayload(headless=True, metadata={"flow": "launch-test"})
    )

    assert warm_pool is not None
    warm_info = session.metadata["warm_pool"]
    assert warm_info["workstation_id"] == "ws-meta"
    origin = session.metadata["browser_origin"]
    assert origin["kind"] == "warm_pool"
    assert origin["mode"] == settings.warm_pool_mode.value
    assert origin["workstation_id"] == "ws-meta"
    assert warm_pool.busy == ["ws-meta"]
    stored_handle = manager._browser_handles[session.id]
    assert stored_handle.ws_endpoint.startswith("ws://warm/ws-meta/")
    events = await publisher.drain()
    assert [event.type for event in events] == [SessionEventType.CREATED]


@pytest.mark.anyio("asyncio")
async def test_update_session_cleans_up_browser() -> None:
    """Transitioning to DEAD should recycle the warm workstation and clear state."""

    publisher = InMemorySessionEventPublisher()
    warm_pool = _StubWarmPoolManager(workstations=["ws-cleanup"])
    manager, warm_pool = _build_manager(
        RunnerSettings(runner_id="runner-cleanup", camoufox_path="/usr/bin/camoufox"),
        publisher,
        warm_pool=warm_pool,
    )
    session = await manager.create_session(SessionCreatePayload())

    updated = await manager.update_session(
        session.id,
        SessionUpdatePayload(status=SessionStatus.DEAD, reason="finished"),
    )

    assert updated.status is SessionStatus.DEAD
    assert updated.ws_endpoint is None
    assert session.id not in manager._browser_handles
    assert warm_pool.releases == ["ws-cleanup"]
    events = await publisher.drain()
    assert [event.type for event in events] == [
        SessionEventType.CREATED,
        SessionEventType.ENDED,
    ]
    assert events[-1].reason == "finished"


@pytest.mark.anyio("asyncio")
async def test_create_session_rolls_back_on_mark_busy_failure() -> None:
    """Session creation should not persist state when warm slot activation fails."""

    class _FailingWarmPool(_StubWarmPoolManager):
        async def mark_busy(self, workstation_id: str) -> WarmPoolSnapshot:  # type: ignore[override]
            raise WarmPoolStateError("slot lost")

    publisher = InMemorySessionEventPublisher()
    warm_pool = _FailingWarmPool(workstations=["ws-fail"])
    manager, warm_pool = _build_manager(
        RunnerSettings(runner_id="runner-fail", camoufox_path="/usr/bin/camoufox"),
        publisher,
        warm_pool=warm_pool,
    )

    with pytest.raises(SessionCapacityError):
        await manager.create_session(SessionCreatePayload())

    assert manager._browser_handles == {}
    assert warm_pool.busy == []
    assert await publisher.drain() == []
