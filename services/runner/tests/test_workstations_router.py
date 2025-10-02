from __future__ import annotations

import pytest
from app.dependencies import get_warm_pool_manager
from app.main import app
from app.warm_pool import WarmPoolSnapshot, WarmPoolState, WarmPoolStateError
from httpx import AsyncClient


class _RouterStubWarmPoolManager:
    """In-memory warm pool double exercised by router tests."""

    def __init__(self) -> None:
        self.started = False
        self.start_calls = 0
        self.states: dict[str, WarmPoolState] = {
            "ws-1": WarmPoolState.IDLE,
            "ws-2": WarmPoolState.ERROR,
        }
        self.restart_calls: list[str] = []
        self.drain_calls: list[str] = []
        self.enable_calls: list[str] = []

    async def start(self) -> None:
        """Record that ``start`` has been invoked."""

        self.started = True
        self.start_calls += 1

    def list_slots(self) -> list[WarmPoolSnapshot]:
        """Return snapshots for all known workstations."""

        if not self.started:
            return []
        return [self._snapshot(workstation_id) for workstation_id in self.states]

    async def restart_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Simulate a restart operation for ``workstation_id``."""

        state = self._require_state(workstation_id)
        if state not in {WarmPoolState.IDLE, WarmPoolState.ERROR}:
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' is {state.value}"
            )
        self.states[workstation_id] = WarmPoolState.IDLE
        self.restart_calls.append(workstation_id)
        return self._snapshot(workstation_id)

    async def drain_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Simulate draining ``workstation_id``."""

        state = self._require_state(workstation_id)
        if state not in {WarmPoolState.IDLE, WarmPoolState.ERROR}:
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' cannot be drained from {state.value}"
            )
        self.states[workstation_id] = WarmPoolState.DRAINING
        self.drain_calls.append(workstation_id)
        return self._snapshot(workstation_id)

    async def enable_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Simulate enabling a previously drained workstation."""

        state = self._require_state(workstation_id)
        if state is not WarmPoolState.DRAINING:
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' is not draining"
            )
        self.states[workstation_id] = WarmPoolState.IDLE
        self.enable_calls.append(workstation_id)
        return self._snapshot(workstation_id)

    def _require_state(self, workstation_id: str) -> WarmPoolState:
        try:
            return self.states[workstation_id]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise WarmPoolStateError(
                f"unknown workstation '{workstation_id}'"
            ) from exc

    def _snapshot(self, workstation_id: str) -> WarmPoolSnapshot:
        state = self.states[workstation_id]
        return WarmPoolSnapshot(
            workstation_id=workstation_id,
            fingerprint_id=None,
            proxy_url=None,
            state=state,
        )


@pytest.fixture
def anyio_backend() -> str:
    """Configure pytest-anyio to use asyncio for these tests."""

    return "asyncio"


@pytest.fixture
def warm_pool_stub() -> _RouterStubWarmPoolManager:
    """Return a fresh warm pool stub for each test."""

    return _RouterStubWarmPoolManager()


@pytest.fixture
async def client(
    warm_pool_stub: _RouterStubWarmPoolManager,
) -> AsyncClient:
    """Yield an ``AsyncClient`` with dependency overrides applied."""

    app.dependency_overrides[get_warm_pool_manager] = lambda: warm_pool_stub
    try:
        async with AsyncClient(app=app, base_url="http://test") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio("asyncio")
async def test_list_workstations_triggers_lazy_start(
    warm_pool_stub: _RouterStubWarmPoolManager, client: AsyncClient
) -> None:
    """``GET /workstations`` should start the pool before listing."""

    response = await client.get("/workstations")

    assert response.status_code == 200
    assert warm_pool_stub.start_calls == 1
    payload = response.json()
    assert {item["workstation_id"] for item in payload} == {"ws-1", "ws-2"}
    states = {item["workstation_id"]: item["state"] for item in payload}
    assert states["ws-1"] == WarmPoolState.IDLE.value
    assert states["ws-2"] == WarmPoolState.ERROR.value


@pytest.mark.anyio("asyncio")
async def test_restart_endpoint_recycles_idle_slot(
    warm_pool_stub: _RouterStubWarmPoolManager, client: AsyncClient
) -> None:
    """``POST /workstations/{id}/restart`` should recycle idle slots."""

    warm_pool_stub.states["ws-1"] = WarmPoolState.IDLE
    response = await client.post("/workstations/ws-1/restart")

    assert response.status_code == 200
    assert warm_pool_stub.restart_calls == ["ws-1"]
    assert response.json()["state"] == WarmPoolState.IDLE.value


@pytest.mark.anyio("asyncio")
async def test_restart_endpoint_returns_conflict_for_busy_slot(
    warm_pool_stub: _RouterStubWarmPoolManager, client: AsyncClient
) -> None:
    """Restart should fail when the workstation is busy."""

    warm_pool_stub.states["ws-1"] = WarmPoolState.BUSY
    response = await client.post("/workstations/ws-1/restart")

    assert response.status_code == 409
    assert "busy" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_restart_endpoint_returns_not_found_for_unknown_id(
    client: AsyncClient
) -> None:
    """Unknown workstations should return a 404 response."""

    response = await client.post("/workstations/ws-404/restart")

    assert response.status_code == 404
    assert "unknown workstation" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_drain_and_enable_cycle(
    warm_pool_stub: _RouterStubWarmPoolManager, client: AsyncClient
) -> None:
    """Draining followed by enabling should transition through states."""

    warm_pool_stub.states["ws-1"] = WarmPoolState.IDLE

    drain_response = await client.post("/workstations/ws-1/drain")
    assert drain_response.status_code == 200
    assert warm_pool_stub.drain_calls == ["ws-1"]
    assert drain_response.json()["state"] == WarmPoolState.DRAINING.value

    enable_response = await client.post("/workstations/ws-1/enable")
    assert enable_response.status_code == 200
    assert warm_pool_stub.enable_calls == ["ws-1"]
    assert enable_response.json()["state"] == WarmPoolState.IDLE.value


@pytest.mark.anyio("asyncio")
async def test_enable_endpoint_conflict_when_not_draining(
    warm_pool_stub: _RouterStubWarmPoolManager, client: AsyncClient
) -> None:
    """Enabling a non-draining workstation should fail with 409."""

    warm_pool_stub.states["ws-1"] = WarmPoolState.IDLE
    response = await client.post("/workstations/ws-1/enable")

    assert response.status_code == 409
    assert "not draining" in response.json()["detail"]
