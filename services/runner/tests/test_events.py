"""Unit tests covering session and workstation event publisher transports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.dependencies.session_manager import (
    get_event_publisher,
    get_runner_settings,
    get_workstation_event_publisher,
)
from app.events import HttpSessionEventPublisher
from app.workstation_events import (
    HttpWorkstationEventPublisher,
    InMemoryWorkstationEventPublisher,
)
from core import (
    Session,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    WorkstationEvent,
    WorkstationEventType,
    WorkstationMeta,
    WorkstationState,
)


@pytest.mark.anyio("asyncio")
async def test_http_session_event_publisher_posts_payload() -> None:
    """The HTTP publisher must POST the serialised payload to the gateway."""

    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    publisher = HttpSessionEventPublisher("https://gateway.local/events", client=client)

    session = Session(
        id=uuid4(),
        runner_id="runner-1",
        status=SessionStatus.READY,
        created_at=datetime.now(tz=UTC),
        last_seen_at=datetime.now(tz=UTC),
        headless=False,
        idle_ttl_seconds=300,
    )
    event = SessionEvent(
        session=session,
        occurred_at=datetime.now(tz=UTC),
        type=SessionEventType.UPDATED,
    )

    await publisher.publish(event)
    await client.aclose()

    assert captured["url"] == "https://gateway.local/events"
    assert captured["json"]["session"]["id"] == str(session.id)


@pytest.mark.anyio("asyncio")
async def test_http_workstation_event_publisher_posts_payload() -> None:
    """Workstation events should be POSTed to the configured endpoint."""

    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(status_code=202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    publisher = HttpWorkstationEventPublisher(
        "https://gateway.local/workstations/events",
        client=client,
    )

    event = WorkstationEvent(
        workstation=WorkstationMeta(
            id="ws-1",
            fingerprint_id="fp-1",
            state=WorkstationState.AVAILABLE,
        ),
        occurred_at=datetime.now(tz=UTC),
        type=WorkstationEventType.UPDATED,
        reason="reserved",
    )

    await publisher.publish(event)
    await client.aclose()

    assert captured["url"] == "https://gateway.local/workstations/events"
    assert captured["json"]["workstation"]["id"] == "ws-1"


@pytest.mark.anyio("asyncio")
async def test_inmemory_workstation_event_publisher_drain() -> None:
    """In-memory workstation publisher should store and drain events FIFO."""

    publisher = InMemoryWorkstationEventPublisher()
    event = WorkstationEvent(
        workstation=WorkstationMeta(
            id="ws-2",
            fingerprint_id="fp-2",
            state=WorkstationState.ASSIGNED,
        ),
        occurred_at=datetime.now(tz=UTC),
        type=WorkstationEventType.UPDATED,
    )

    await publisher.publish(event)
    drained = await publisher.drain()

    assert drained == [event]


def test_get_event_publisher_prefers_http_when_endpoint_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner settings with EVENT_ENDPOINT should yield the HTTP publisher."""

    get_runner_settings.cache_clear()
    get_event_publisher.cache_clear()
    monkeypatch.setenv("EVENT_ENDPOINT", "https://gateway.local/events")

    try:
        publisher = get_event_publisher()
        assert isinstance(publisher, HttpSessionEventPublisher)
    finally:
        monkeypatch.delenv("EVENT_ENDPOINT")
        get_event_publisher.cache_clear()
        get_runner_settings.cache_clear()


def test_get_workstation_event_publisher_prefers_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """WORKSTATION_EVENT_ENDPOINT should activate the HTTP publisher."""

    get_runner_settings.cache_clear()
    get_workstation_event_publisher.cache_clear()
    monkeypatch.setenv(
        "WORKSTATION_EVENT_ENDPOINT",
        "https://gateway.local/workstations/events",
    )

    try:
        publisher = get_workstation_event_publisher()
        assert isinstance(publisher, HttpWorkstationEventPublisher)
    finally:
        monkeypatch.delenv("WORKSTATION_EVENT_ENDPOINT")
        get_workstation_event_publisher.cache_clear()
        get_runner_settings.cache_clear()
