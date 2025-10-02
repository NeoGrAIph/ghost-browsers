"""Integration tests covering the warm workstation management API."""

from __future__ import annotations

from typing import Any

import pytest
from app.dependencies.session_manager import (
    get_warm_pool_manager,
    get_workstation_event_publisher,
)
from app.events import InMemoryWorkstationEventPublisher
from app.main import app
from app.warm_pool import (
    WarmPoolReservation,
    WarmPoolSnapshot,
    WarmPoolState,
    WarmPoolStateError,
)
from core.models import WorkstationEventType, WorkstationState
from httpx import AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    """Force pytest-anyio to use asyncio for FastAPI integration tests."""

    return "asyncio"


class _StubWarmHandle:
    """Minimal placeholder representing a warm workstation browser handle."""

    def __init__(self, workstation_id: str) -> None:
        self.workstation_id = workstation_id


class _StubWarmPoolManager:
    """Async test double implementing the warm pool interface."""

    def __init__(self, *, workstations: list[str] | None = None) -> None:
        self._workstations = workstations or ["ws-1", "ws-2", "ws-3"]
        self._slots: dict[str, dict[str, Any]] = {
            workstation: {
                "state": WarmPoolState.IDLE,
                "fingerprint": f"fp-{workstation}",
                "proxy": None,
            }
            for workstation in self._workstations
        }
        self.reservations: list[str] = []
        self.busy: list[str] = []
        self.cancellations: list[str] = []
        self.releases: list[str] = []

    async def start(self) -> None:
        """Real manager initialises slots; stub does nothing."""

        return None

    def list_slots(self) -> list[WarmPoolSnapshot]:
        """Return current slot snapshots for the warm pool."""

        return [
            WarmPoolSnapshot(
                workstation_id=workstation,
                fingerprint_id=slot["fingerprint"],
                proxy_url=slot["proxy"],
                state=slot["state"],
            )
            for workstation, slot in self._slots.items()
        ]

    async def reserve_slot(
        self, workstation_id: str | None = None
    ) -> WarmPoolReservation:
        """Reserve the requested workstation or the first idle slot."""

        target = workstation_id or self._first_idle()
        slot = self._require_slot(target)
        if slot["state"] is not WarmPoolState.IDLE:
            raise WarmPoolStateError(f"workstation '{target}' is not idle")
        slot["state"] = WarmPoolState.RESERVED
        self.reservations.append(target)
        snapshot = WarmPoolSnapshot(
            workstation_id=target,
            fingerprint_id=slot["fingerprint"],
            proxy_url=slot["proxy"],
            state=WarmPoolState.RESERVED,
        )
        env = {
            "CAMOUFOX_WORKSTATION_ID": target,
            "CAMOUFOX_FINGERPRINT_ID": slot["fingerprint"],
        }
        return WarmPoolReservation(
            snapshot=snapshot,
            handle=_StubWarmHandle(target),
            environment=env,
        )

    async def mark_busy(self, workstation_id: str) -> WarmPoolSnapshot:
        """Mark a reserved workstation as busy."""

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
        """Return a reserved workstation to idle."""

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
        """Recycle a busy workstation back to idle."""

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
            proxy_url=slot["proxy"],
            state=WarmPoolState.IDLE,
        )

    def _require_slot(self, workstation_id: str) -> dict[str, Any]:
        try:
            return self._slots[workstation_id]
        except KeyError as exc:
            raise WarmPoolStateError(
                f"unknown workstation '{workstation_id}'"
            ) from exc

    def _first_idle(self) -> str:
        for workstation_id, slot in self._slots.items():
            if slot["state"] is WarmPoolState.IDLE:
                return workstation_id
        raise WarmPoolStateError("no idle warm workstations available")


async def _override_dependencies(
    warm_pool: _StubWarmPoolManager,
    publisher: InMemoryWorkstationEventPublisher,
) -> None:
    """Replace warm pool and event publisher dependencies for the test scope."""

    get_warm_pool_manager.cache_clear()
    get_workstation_event_publisher.cache_clear()
    app.dependency_overrides[get_warm_pool_manager] = lambda: warm_pool
    app.dependency_overrides[get_workstation_event_publisher] = lambda: publisher


def _reset_overrides() -> None:
    """Clear FastAPI dependency overrides set for integration tests."""

    app.dependency_overrides.clear()


@pytest.mark.anyio("asyncio")
async def test_reserve_workstation_success() -> None:
    """``POST /workstations/reserve`` should reserve a slot and emit an event."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-alpha"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-alpha"}
            )
    finally:
        _reset_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"]["workstation_id"] == "ws-alpha"
    assert body["snapshot"]["state"] == WarmPoolState.RESERVED.value
    assert body["environment"] == {
        "CAMOUFOX_WORKSTATION_ID": "ws-alpha",
        "CAMOUFOX_FINGERPRINT_ID": "fp-ws-alpha",
    }
    assert warm_pool.reservations == ["ws-alpha"]
    events = await publisher.drain()
    assert len(events) == 1
    event = events[0]
    assert event.type is WorkstationEventType.UPDATED
    assert event.reason == "reserved"
    assert event.workstation.id == "ws-alpha"
    assert event.workstation.state is WorkstationState.PROVISIONING
    assert event.workstation.metadata["launch_env"] == body["environment"]


@pytest.mark.anyio("asyncio")
async def test_reserve_workstation_conflict_when_not_idle() -> None:
    """Reserving an already reserved workstation should return HTTP 409."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-beta"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            first = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-beta"}
            )
            assert first.status_code == 200
            response = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-beta"}
            )
    finally:
        _reset_overrides()

    assert response.status_code == 409
    assert "not idle" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_reserve_workstation_unknown_identifier() -> None:
    """Unknown workstations should surface as HTTP 404 responses."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-known"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-missing"}
            )
    finally:
        _reset_overrides()

    assert response.status_code == 404
    assert response.json()["detail"].startswith("unknown workstation")


@pytest.mark.anyio("asyncio")
async def test_mark_workstation_busy_success() -> None:
    """``POST /workstations/{id}/busy`` should transition to busy and emit an event."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-busy"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            reserve = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-busy"}
            )
            assert reserve.status_code == 200
            response = await client.post("/workstations/ws-busy/busy")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    assert response.json()["snapshot"]["state"] == WarmPoolState.BUSY.value
    assert warm_pool.busy == ["ws-busy"]
    events = await publisher.drain()
    assert [event.reason for event in events][-1] == "busy"
    assert events[-1].workstation.state is WorkstationState.ASSIGNED


@pytest.mark.anyio("asyncio")
async def test_mark_workstation_busy_conflict_when_idle() -> None:
    """Marking a workstation busy without a reservation should fail with 409."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-idle"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-idle/busy")
    finally:
        _reset_overrides()

    assert response.status_code == 409
    assert "not reserved" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_mark_workstation_busy_unknown_identifier() -> None:
    """Busy endpoint should return 404 for unknown workstations."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-catalog"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-absent/busy")
    finally:
        _reset_overrides()

    assert response.status_code == 404
    assert response.json()["detail"].startswith("unknown workstation")


@pytest.mark.anyio("asyncio")
async def test_cancel_reservation_success() -> None:
    """Cancelling a reservation should return the workstation to idle."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-cancel"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            reserve = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-cancel"}
            )
            assert reserve.status_code == 200
            response = await client.post("/workstations/ws-cancel/cancel")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    assert response.json()["snapshot"]["state"] == WarmPoolState.IDLE.value
    assert warm_pool.cancellations == ["ws-cancel"]
    events = await publisher.drain()
    assert events[-1].reason == "cancelled"
    assert events[-1].workstation.state is WorkstationState.AVAILABLE


@pytest.mark.anyio("asyncio")
async def test_cancel_reservation_conflict_when_idle() -> None:
    """Cancelling a workstation without a reservation should raise HTTP 409."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-free"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-free/cancel")
    finally:
        _reset_overrides()

    assert response.status_code == 409
    assert "not reserved" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_cancel_reservation_unknown_identifier() -> None:
    """Cancel endpoint should surface unknown workstations as HTTP 404."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-list"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-missing/cancel")
    finally:
        _reset_overrides()

    assert response.status_code == 404
    assert response.json()["detail"].startswith("unknown workstation")


@pytest.mark.anyio("asyncio")
async def test_release_workstation_success() -> None:
    """Releasing a busy workstation should recycle the slot and emit events."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-release"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            reserve = await client.post(
                "/workstations/reserve", json={"workstation_id": "ws-release"}
            )
            assert reserve.status_code == 200
            busy = await client.post("/workstations/ws-release/busy")
            assert busy.status_code == 200
            response = await client.post("/workstations/ws-release/release")
    finally:
        _reset_overrides()

    assert response.status_code == 200
    assert response.json()["snapshot"]["state"] == WarmPoolState.IDLE.value
    assert warm_pool.releases == ["ws-release"]
    events = await publisher.drain()
    assert events[-1].reason == "released"
    assert events[-1].type is WorkstationEventType.RELEASED
    assert events[-1].workstation.state is WorkstationState.AVAILABLE


@pytest.mark.anyio("asyncio")
async def test_release_workstation_conflict_when_idle() -> None:
    """Releasing an idle workstation should report HTTP 409."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-idle-release"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-idle-release/release")
    finally:
        _reset_overrides()

    assert response.status_code == 409
    assert "cannot be recycled" in response.json()["detail"]


@pytest.mark.anyio("asyncio")
async def test_release_workstation_unknown_identifier() -> None:
    """Release endpoint should return HTTP 404 for unknown identifiers."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-known-release"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/workstations/ws-ghost/release")
    finally:
        _reset_overrides()

    assert response.status_code == 404
    assert response.json()["detail"].startswith("unknown workstation")


@pytest.mark.anyio("asyncio")
async def test_workstation_event_stream_tracks_full_lifecycle() -> None:
    """A full reserve → busy → release flow should emit ordered events."""

    warm_pool = _StubWarmPoolManager(workstations=["ws-flow"])
    publisher = InMemoryWorkstationEventPublisher()
    await _override_dependencies(warm_pool, publisher)

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            await client.post("/workstations/reserve", json={"workstation_id": "ws-flow"})
            await client.post("/workstations/ws-flow/busy")
            await client.post("/workstations/ws-flow/release")
    finally:
        _reset_overrides()

    events = await publisher.drain()
    assert [event.reason for event in events] == ["reserved", "busy", "released"]
    assert [event.type for event in events] == [
        WorkstationEventType.UPDATED,
        WorkstationEventType.UPDATED,
        WorkstationEventType.RELEASED,
    ]
    assert [event.workstation.state for event in events] == [
        WorkstationState.PROVISIONING,
        WorkstationState.ASSIGNED,
        WorkstationState.AVAILABLE,
    ]
