"""Integration tests covering session and workstation event publishers."""

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
)
from app.events import (
    HttpSessionEventPublisher,
    SseWorkstationEventPublisher,
    WebSocketWorkstationEventPublisher,
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


@pytest.mark.anyio("asyncio")
async def test_sse_workstation_event_publisher_formats_frame() -> None:
    """SSE publisher should encode workstation events as SSE frames."""

    frames: list[str] = []

    async def push(frame: str) -> None:
        frames.append(frame)

    publisher = SseWorkstationEventPublisher(push)
    event = WorkstationEvent(
        type=WorkstationEventType.STATE_CHANGED,
        workstation=WorkstationMeta(
            id="ws-1",
            fingerprint_id="fp-1",
            state=WorkstationState.AVAILABLE,
        ),
        occurred_at=datetime.now(tz=UTC),
        reason="reserved",
    )

    await publisher.publish(event)

    assert frames, "Frame should be emitted"
    assert frames[0].startswith(f"event: {event.type.value}\n")
    payload = frames[0].split("data: ", 1)[1].strip()
    body = json.loads(payload)
    assert body["workstation"]["id"] == "ws-1"


@pytest.mark.anyio("asyncio")
async def test_websocket_workstation_event_publisher_forwards_payload() -> None:
    """WebSocket publisher should forward JSON compatible payloads."""

    messages: list[dict[str, Any]] = []

    async def push(message: dict[str, Any]) -> None:
        messages.append(message)

    publisher = WebSocketWorkstationEventPublisher(push)
    event = WorkstationEvent(
        type=WorkstationEventType.RECYCLED,
        workstation=WorkstationMeta(
            id="ws-2",
            fingerprint_id="fp-2",
            state=WorkstationState.AVAILABLE,
        ),
        occurred_at=datetime.now(tz=UTC),
        reason="restarted",
    )

    await publisher.publish(event)

    assert messages, "Message should be emitted"
    assert messages[0]["type"] == event.type.value
    assert messages[0]["event"]["workstation"]["id"] == "ws-2"
