"""Unit tests for the shared core models and utilities."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from core import (
    InMemorySessionEventBridge,
    Runner,
    RunnerState,
    Session,
    SessionEvent,
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
    StartUrlWait,
)
from pydantic import ValidationError


def build_session(**overrides) -> Session:
    """Build a session instance with sensible defaults for tests.

    Args:
        **overrides: Optional keyword overrides applied to the base payload.

    Returns:
        Session: Constructed session object ready for assertions.
    """

    defaults = dict(overrides)
    now = datetime.now(tz=timezone.utc)
    created_at = defaults.pop("created_at", now)
    last_seen_at = defaults.pop("last_seen_at", defaults.pop("updated_at", created_at))

    data = {
        "id": uuid4(),
        "runner_id": "runner-1",
        "status": SessionStatus.INIT,
        "created_at": created_at,
        "last_seen_at": last_seen_at,
        "headless": False,
        "idle_ttl_seconds": 300,
        "browser": "camoufox",
        "labels": {"env": "test"},
        "start_url_wait": StartUrlWait.LOAD,
        "metadata": {"key": "value"},
    }
    data.update(defaults)
    return Session(**data)


def test_runner_defaults_available_slots_to_total() -> None:
    """Runner without explicit available slots derives them from total_slots."""

    runner = Runner(id="runner-1", base_url="http://runner:8080", total_slots=4)
    assert runner.available_slots == 4
    assert runner.healthy is True
    assert runner.state == RunnerState.STARTING


def test_runner_id_rejects_whitespace_only_identifiers() -> None:
    """Runner identifiers consisting of whitespace should be rejected."""

    with pytest.raises(ValidationError):
        Runner(id="   ", base_url="http://runner:8080", total_slots=1)


def test_runner_rejects_invalid_slot_count() -> None:
    """Runner raises an error when available slots exceed total slots."""

    with pytest.raises(ValidationError):
        Runner(
            id="runner-1",
            base_url="http://runner:8080",
            total_slots=2,
            available_slots=3,
        )


def test_session_temporal_invariants() -> None:
    """Session enforces timestamp ordering and status relationships."""

    now = datetime.now(tz=timezone.utc)
    with pytest.raises(ValidationError):
        build_session(last_seen_at=now - timedelta(seconds=1))

    with pytest.raises(ValidationError):
        build_session(ended_at=now - timedelta(seconds=1))

    ended = now + timedelta(seconds=1)
    build_session(status=SessionStatus.DEAD, ended_at=ended)


def test_session_vnc_ttl_limit() -> None:
    """Session VNC details reject TTL values above the configured limit."""

    SessionVncDetails(websocket_url="wss://vnc/ws", token="abc", token_ttl_seconds=300)
    with pytest.raises(ValidationError):
        SessionVncDetails(websocket_url="wss://vnc/ws", token="abc", token_ttl_seconds=301)

    with pytest.raises(ValidationError):
        SessionVncDetails(websocket_url="wss://vnc/ws", token="abc", token_ttl_seconds=None)


def test_session_proxy_requires_any_value() -> None:
    """Proxy settings require at least one URL to be provided."""

    with pytest.raises(ValidationError):
        SessionProxySettings()

    settings = SessionProxySettings(http="http://proxy:3128")
    assert str(settings.http) == "http://proxy:3128/"


def test_session_runner_id_rejects_whitespace_only_identifiers() -> None:
    """Session runner_id should not allow blank values after trimming."""

    with pytest.raises(ValidationError):
        build_session(runner_id="   ")


def test_session_event_validations() -> None:
    """Session events enforce semantic constraints for lifecycle transitions."""

    now = datetime.now(tz=timezone.utc)
    session = build_session(status=SessionStatus.INIT)
    SessionEvent(session=session, occurred_at=now, type=SessionEventType.CREATED)

    with pytest.raises(ValidationError):
        SessionEvent(
            session=build_session(status=SessionStatus.TERMINATING),
            occurred_at=now,
            type=SessionEventType.CREATED,
        )

    ended_session = build_session(
        status=SessionStatus.DEAD,
        created_at=now,
        last_seen_at=now,
        ended_at=now,
    )
    SessionEvent(session=ended_session, occurred_at=now, type=SessionEventType.ENDED)

    with pytest.raises(ValidationError):
        SessionEvent(
            session=build_session(status=SessionStatus.READY),
            occurred_at=now,
            type=SessionEventType.ENDED,
        )


def test_session_serialization_round_trip() -> None:
    """Session instances serialize and deserialize without data loss."""

    vnc = SessionVncDetails(
        websocket_url="wss://vnc/ws",
        http_url="https://vnc/view",
        token="abc",
        token_ttl_seconds=60,
    )
    proxy = SessionProxySettings(http="http://proxy:3128")
    session = build_session(
        status=SessionStatus.READY,
        vnc=vnc,
        proxy=proxy,
        ws_endpoint="/sessions/runner-1/session/ws",
    )

    dumped = session.model_dump(mode="json")
    restored = Session.model_validate(dumped)
    assert restored == session


def test_session_event_is_terminal_property() -> None:
    """SessionEvent exposes a convenience flag for terminal events."""

    now = datetime.now(tz=timezone.utc)
    active_event = SessionEvent(
        session=build_session(status=SessionStatus.READY),
        occurred_at=now,
    )
    finished_event = SessionEvent(
        session=build_session(
            status=SessionStatus.DEAD,
            created_at=now,
            ended_at=now,
            last_seen_at=now,
        ),
        occurred_at=now,
        type=SessionEventType.ENDED,
    )

    assert active_event.is_terminal is False
    assert finished_event.is_terminal is True


def test_inmemory_bridge_fanout() -> None:
    """In-memory bridge delivers published events to all subscribers."""

    async def run() -> None:
        """Exercise fan-out behaviour across multiple subscribers."""

        bridge = InMemorySessionEventBridge()
        session = build_session(status=SessionStatus.READY)
        event = SessionEvent(session=session, occurred_at=datetime.now(tz=timezone.utc))

        stream_one = await bridge.subscribe()
        stream_two = await bridge.subscribe()

        task_one = asyncio.create_task(stream_one.__anext__())
        task_two = asyncio.create_task(stream_two.__anext__())

        await bridge.publish(event)

        assert await task_one is event
        assert await task_two is event

        await stream_one.aclose()
        await stream_two.aclose()

    asyncio.run(run())


def test_inmemory_bridge_replay_latest_on_subscribe() -> None:
    """Subscribers can opt-in to replay the most recent event on subscribe."""

    async def run() -> None:
        """Exercise the replay mode for a reconnecting subscriber."""

        bridge = InMemorySessionEventBridge()
        event = SessionEvent(
            session=build_session(status=SessionStatus.READY),
            occurred_at=datetime.now(tz=timezone.utc),
        )

        await bridge.publish(event)
        stream = await bridge.subscribe(replay_latest=True)

        replayed = await stream.__anext__()
        assert replayed is event

        await stream.aclose()

    asyncio.run(run())
