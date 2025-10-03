"""Unit tests for the Runner command client."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.services.runner_client import (
    RunnerCommandClient,
    RunnerCommandError,
    SessionCreateCommand,
    SessionUpdateCommand,
)
from core import Runner, Session, SessionStatus

pytestmark = pytest.mark.anyio


@pytest.fixture()
def sample_runner() -> Runner:
    """Return a runner descriptor used across runner client tests."""

    return Runner(
        id="runner-1",
        base_url="http://runner.example",
        total_slots=1,
        supports_vnc=True,
    )


def _session_payload(**overrides: Any) -> dict[str, Any]:
    """Build a serialisable ``Session`` payload for HTTP responses."""

    now = datetime.now(tz=UTC)
    session = Session(
        id=overrides.get("id", uuid4()),
        runner_id="runner-1",
        status=overrides.get("status", SessionStatus.INIT),
        created_at=now,
        last_seen_at=now,
        headless=overrides.get("headless", False),
        idle_ttl_seconds=300,
        labels=overrides.get("labels", {"region": "eu-central"}),
    )
    return session.model_dump(mode="json")


@pytest.fixture()
def anyio_backend() -> str:
    """Ensure tests execute on the asyncio backend only."""

    return "asyncio"


async def test_create_session_issues_post(sample_runner: Runner) -> None:
    """``create_session`` posts the rendered payload to ``/sessions``."""

    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=_session_payload())

    command = SessionCreateCommand(
        runner_id="runner-1",
        browser_name="Chrome",
        region="eu-central",
        proxy_id="proxy-9",
    )
    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))

    session = await client.create_session(sample_runner, command)

    assert session.runner_id == sample_runner.id
    assert requests
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/sessions"
    payload = json.loads(requests[0].content.decode())
    assert payload == command.to_runner_payload()


async def test_update_session_issues_patch(sample_runner: Runner) -> None:
    """``update_session`` proxies the partial update payload to the runner."""

    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_session_payload(status=SessionStatus.READY))

    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))
    command = SessionUpdateCommand(status=SessionStatus.READY)
    session_id = uuid4()

    session = await client.update_session(sample_runner, session_id, command)

    assert session.status is SessionStatus.READY
    assert requests
    assert requests[0].method == "PATCH"
    assert requests[0].url.path.endswith(f"/sessions/{session_id}")
    payload = json.loads(requests[0].content.decode())
    assert payload == command.to_runner_payload()


async def test_delete_session_issues_delete(sample_runner: Runner) -> None:
    """``delete_session`` forwards the request and returns the final state."""

    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_session_payload(status=SessionStatus.DEAD))

    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))
    session_id = uuid4()

    session = await client.delete_session(sample_runner, session_id)

    assert session.status is SessionStatus.DEAD
    assert requests
    assert requests[0].method == "DELETE"
    assert requests[0].url.path.endswith(f"/sessions/{session_id}")


async def test_list_sessions_returns_validated_models(sample_runner: Runner) -> None:
    """``list_sessions`` issues ``GET /sessions`` and validates each entry."""

    requests: list[httpx.Request] = []
    payload = [_session_payload(), _session_payload()]

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))

    sessions = await client.list_sessions(sample_runner)

    assert requests
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/sessions"
    assert [str(session.id) for session in sessions] == [item["id"] for item in payload]


async def test_list_sessions_rejects_invalid_entries(sample_runner: Runner) -> None:
    """Non-mapping elements in the response should trigger ``RunnerCommandError``."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["invalid"])

    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))

    with pytest.raises(RunnerCommandError):
        await client.list_sessions(sample_runner)


async def test_create_session_raises_on_unexpected_status(sample_runner: Runner) -> None:
    """Non-201 responses for create commands raise ``RunnerCommandError``."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_session_payload())

    client = RunnerCommandClient(transport=httpx.MockTransport(_handler))
    command = SessionCreateCommand(
        runner_id="runner-1",
        browser_name="Chrome",
        region="eu-central",
    )

    with pytest.raises(RunnerCommandError):
        await client.create_session(sample_runner, command)
