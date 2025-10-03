"""Tests covering runner discovery backends and reconciliation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.config import GatewaySettings
from app.services.discovery import (
    HttpRunnerDiscoveryBackend,
    RunnerDiscoveryService,
    RunnerSyncResult,
    StaticRunnerDiscoveryBackend,
    purge_sessions_for_missing_runners,
)
from app.services.runner_registry import RunnerRegistry
from app.services.session_registry import SessionRegistry
from core import Runner, Session, SessionStatus


@pytest.fixture()
def anyio_backend() -> str:
    """Run AnyIO-powered tests on the asyncio backend for determinism."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_static_discovery_registers_runners() -> None:
    """Static backend should register all configured runners on refresh."""

    settings = GatewaySettings(
        discovery_mode="static",
        runners=[
            Runner(id="runner-1", base_url="http://runner-1", total_slots=2),
            Runner(id="runner-2", base_url="http://runner-2", total_slots=1),
        ],
    )
    registry = RunnerRegistry()
    sessions = SessionRegistry()
    service = RunnerDiscoveryService(
        settings=settings,
        runner_registry=registry,
        session_registry=sessions,
        backend=StaticRunnerDiscoveryBackend(settings.runners),
    )

    result = await service.refresh()
    assert isinstance(result, RunnerSyncResult)
    assert result.added == {"runner-1", "runner-2"}
    assert result.updated == set()
    stored = await registry.list()
    assert {runner.id for runner in stored} == {"runner-1", "runner-2"}


@pytest.mark.anyio("asyncio")
async def test_http_discovery_updates_existing_and_adds_new_runners() -> None:
    """HTTP backend should surface updates and newly added runners."""

    payloads: list[list[dict[str, Any]]] = [
        [
            {"id": "runner-1", "base_url": "http://runner-1", "total_slots": 1},
        ],
        [
            {"id": "runner-1", "base_url": "http://runner-1b", "total_slots": 2},
            {"id": "runner-2", "base_url": "http://runner-2", "total_slots": 1},
        ],
    ]
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        index = min(call_count, len(payloads) - 1)
        call_count += 1
        assert request.url == httpx.URL("http://discovery.local/runners")
        return httpx.Response(200, json=payloads[index])

    settings = GatewaySettings(
        discovery_mode="http",
        discovery_endpoint="http://discovery.local/runners",
    )
    registry = RunnerRegistry()
    service = RunnerDiscoveryService(
        settings=settings,
        runner_registry=registry,
        backend=HttpRunnerDiscoveryBackend(
            endpoint=settings.discovery_endpoint,
            transport=httpx.MockTransport(_handler),
        ),
    )

    first = await service.refresh()
    assert first.added == {"runner-1"}
    stored = await registry.get("runner-1")
    assert stored is not None
    assert str(stored.base_url) == "http://runner-1/"

    second = await service.refresh()
    assert second.added == {"runner-2"}
    assert second.updated == {"runner-1"}
    updated = await registry.get("runner-1")
    assert updated is not None
    assert str(updated.base_url) == "http://runner-1b/"


@pytest.mark.anyio("asyncio")
async def test_removed_runners_drop_bindings_and_sessions() -> None:
    """Removed runners should lose WS bindings and associated sessions."""

    now = datetime.now(tz=UTC)
    session_registry = SessionRegistry()
    runner_registry = RunnerRegistry(
        [
            Runner(id="runner-a", base_url="http://runner-a", total_slots=1),
            Runner(id="runner-b", base_url="http://runner-b", total_slots=1),
        ]
    )

    session = Session(
        id=uuid4(),
        runner_id="runner-b",
        status=SessionStatus.INIT,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        labels={},
    )
    await session_registry.add(session)
    await runner_registry.register_session_ws_endpoint(
        session.id,
        runner_id=session.runner_id,
        target="ws://runner-b/playwright/session",
    )

    payloads: list[list[dict[str, Any]]] = [
        [
            {"id": "runner-a", "base_url": "http://runner-a", "total_slots": 1},
            {"id": "runner-b", "base_url": "http://runner-b", "total_slots": 1},
        ],
        [
            {"id": "runner-a", "base_url": "http://runner-a", "total_slots": 1},
        ],
    ]
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        index = min(call_count, len(payloads) - 1)
        call_count += 1
        return httpx.Response(200, json=payloads[index])

    settings = GatewaySettings(
        discovery_mode="http",
        discovery_endpoint="http://discovery.local/runners",
    )
    service = RunnerDiscoveryService(
        settings=settings,
        runner_registry=runner_registry,
        session_registry=session_registry,
        backend=HttpRunnerDiscoveryBackend(
            endpoint=settings.discovery_endpoint,
            transport=httpx.MockTransport(_handler),
        ),
    )

    await service.refresh()  # initial load populates known ids
    result = await service.refresh()
    assert result.removed == {"runner-b"}

    await purge_sessions_for_missing_runners(
        session_registry,
        runner_registry,
        result.removed,
    )

    assert await runner_registry.get("runner-b") is None
    assert await runner_registry.resolve_session_ws_target(session.id) is None
    assert await session_registry.list() == []


@pytest.mark.anyio("asyncio")
async def test_purge_sessions_tolerates_pre_deleted_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Session cleanup should ignore entries concurrently removed elsewhere."""

    now = datetime.now(tz=UTC)
    session_registry = SessionRegistry()
    runner_registry = RunnerRegistry()

    missing_runner_ids = {"runner-z"}
    first = Session(
        id=uuid4(),
        runner_id="runner-z",
        status=SessionStatus.INIT,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        labels={},
    )
    second = Session(
        id=uuid4(),
        runner_id="runner-z",
        status=SessionStatus.INIT,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
        labels={},
    )
    await session_registry.add(first)
    await session_registry.add(second)
    await runner_registry.register_session_ws_endpoint(
        first.id,
        runner_id=first.runner_id,
        target="ws://runner-z/first",
    )
    await runner_registry.register_session_ws_endpoint(
        second.id,
        runner_id=second.runner_id,
        target="ws://runner-z/second",
    )

    original_delete = session_registry.delete

    async def _delete_with_race(session_id: UUID) -> None:
        if session_id == first.id:
            await original_delete(session_id)
            raise KeyError("Session not found")
        await original_delete(session_id)

    monkeypatch.setattr(session_registry, "delete", _delete_with_race)

    removed = await purge_sessions_for_missing_runners(
        session_registry,
        runner_registry,
        missing_runner_ids,
    )

    assert removed == [second.id]
    assert await session_registry.list() == []
    assert await runner_registry.resolve_session_ws_target(first.id) is None
    assert await runner_registry.resolve_session_ws_target(second.id) is None
