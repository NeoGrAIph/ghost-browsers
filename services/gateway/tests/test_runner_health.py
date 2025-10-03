"""Tests covering the runner health polling client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.services.runner_health import RunnerHealthClient
from app.services.runner_registry import RunnerRegistry
from core import Runner


@pytest.fixture()
def anyio_backend() -> str:
    """Force AnyIO to run on asyncio for predictable unit tests."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_probe_updates_registry_on_success() -> None:
    """Successful probes should update health and slot information."""

    runner = Runner(id="runner-1", base_url="http://runner-1", total_slots=1)
    registry = RunnerRegistry([runner])

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "runner_id": "runner-1",
                "slots": {"total": 4, "available": 2},
                "vnc": {"enabled": True},
            },
        )

    client = RunnerHealthClient(transport=httpx.MockTransport(_handler))

    updated = await client.probe(runner, registry)
    assert updated is not None
    assert updated.healthy is True
    assert updated.available_slots == 2
    assert updated.total_slots == 4
    assert updated.supports_vnc is True
    assert updated.last_heartbeat_at is not None
    assert updated.last_heartbeat_at.tzinfo is UTC


@pytest.mark.anyio("asyncio")
async def test_probe_marks_runner_unhealthy_on_failure() -> None:
    """Network failures should mark the runner unhealthy without new heartbeat."""

    heartbeat = datetime.now(tz=UTC) - timedelta(minutes=5)
    runner = Runner(
        id="runner-2",
        base_url="http://runner-2",
        total_slots=1,
        last_heartbeat_at=heartbeat,
    )
    registry = RunnerRegistry([runner])

    def _handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - defensive
        raise AssertionError("handler should not be called")

    def _failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    client = RunnerHealthClient(transport=httpx.MockTransport(_failing_handler))

    updated = await client.probe(runner, registry)
    assert updated is None

    stored = await registry.get("runner-2")
    assert stored is not None
    assert stored.healthy is False
    assert stored.last_heartbeat_at == heartbeat
