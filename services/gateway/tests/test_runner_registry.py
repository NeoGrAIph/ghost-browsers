"""Unit tests for the runner registry selection and health updates."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.services.runner_registry import RunnerRegistry
from core import Runner, RunnerState


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO to use asyncio to avoid optional trio dependency."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_select_next_filters_by_health_and_vnc() -> None:
    """``select_next`` should ignore unhealthy or VNC-incompatible runners."""

    registry = RunnerRegistry(
        [
            Runner(
                id="runner-a",
                base_url="http://runner-a",
                total_slots=1,
                supports_vnc=True,
            ),
            Runner(
                id="runner-b",
                base_url="http://runner-b",
                total_slots=1,
                supports_vnc=False,
            ),
        ]
    )

    await registry.record_health(
        "runner-a",
        healthy=False,
        heartbeat_at=datetime.now(tz=UTC),
    )
    runner = await registry.select_next(requires_vnc=True)
    assert runner is None

    await registry.record_health(
        "runner-a",
        healthy=True,
        heartbeat_at=datetime.now(tz=UTC),
    )
    runner = await registry.select_next(requires_vnc=True)
    assert runner is not None and runner.id == "runner-a"


@pytest.mark.anyio("asyncio")
async def test_select_next_rotates_candidates() -> None:
    """Round-robin selection should iterate across available runners."""

    registry = RunnerRegistry(
        [
            Runner(id="runner-1", base_url="http://runner-1", total_slots=1),
            Runner(id="runner-2", base_url="http://runner-2", total_slots=1),
            Runner(id="runner-3", base_url="http://runner-3", total_slots=1),
        ]
    )

    picks = [
        await registry.select_next(requires_vnc=False)
        for _ in range(5)
    ]
    assert [runner.id for runner in picks if runner is not None][:3] == [
        "runner-1",
        "runner-2",
        "runner-3",
    ]


@pytest.mark.anyio("asyncio")
async def test_select_next_skips_exhausted_or_busy_runners() -> None:
    """Exhausted slots or non-accepting states should be ignored by selector."""

    registry = RunnerRegistry(
        [
            Runner(
                id="runner-busy",
                base_url="http://runner-busy",
                total_slots=1,
                available_slots=0,
                state=RunnerState.BUSY,
            ),
            Runner(
                id="runner-empty",
                base_url="http://runner-empty",
                total_slots=1,
                available_slots=0,
                state=RunnerState.IDLE,
            ),
            Runner(
                id="runner-free",
                base_url="http://runner-free",
                total_slots=1,
                available_slots=1,
                state=RunnerState.IDLE,
            ),
        ]
    )

    first_pick = await registry.select_next(requires_vnc=False)
    second_pick = await registry.select_next(requires_vnc=False)

    assert first_pick is not None and first_pick.id == "runner-free"
    assert second_pick is not None and second_pick.id == "runner-free"


@pytest.mark.anyio("asyncio")
async def test_record_health_updates_snapshot() -> None:
    """Health records should persist timestamps and slot information."""

    registry = RunnerRegistry(
        [
            Runner(
                id="runner-health",
                base_url="http://runner-health",
                total_slots=2,
            )
        ]
    )
    observed = datetime.now(tz=UTC)

    updated = await registry.record_health(
        "runner-health",
        healthy=True,
        heartbeat_at=observed,
        total_slots=4,
        available_slots=3,
        supports_vnc=True,
    )

    assert updated is not None
    assert updated.last_heartbeat_at == observed
    assert updated.total_slots == 4
    assert updated.available_slots == 3
    assert updated.supports_vnc is True


@pytest.mark.anyio("asyncio")
async def test_session_ws_binding_registration() -> None:
    """RunnerRegistry stores runner and public endpoints for sessions."""

    registry = RunnerRegistry(
        [Runner(id="runner-1", base_url="http://runner-1", total_slots=1)]
    )
    session_id = UUID("00000000-0000-0000-0000-000000000001")

    public = await registry.register_session_ws_endpoint(
        session_id,
        runner_id="runner-1",
        target="ws://runner-1/playwright/1",
    )
    assert public == "/sessions/00000000-0000-0000-0000-000000000001/ws"
    assert (
        await registry.resolve_session_ws_target(session_id)
        == "ws://runner-1/playwright/1"
    )
    assert (
        await registry.resolve_session_ws_public(session_id)
        == public
    )

    await registry.register_session_ws_endpoint(
        session_id,
        runner_id="runner-1",
        target=None,
    )
    assert await registry.resolve_session_ws_target(session_id) is None
