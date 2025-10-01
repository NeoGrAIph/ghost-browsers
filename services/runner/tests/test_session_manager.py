"""Unit tests for :mod:`app.session_manager`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import RunnerSettings
from app.events import InMemorySessionEventPublisher
from app.session_manager import SessionCreatePayload, SessionManager, SessionUpdatePayload
from core.models import (
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
)


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_create_session_emits_event_and_vnc_stub() -> None:
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
    manager = SessionManager(settings, publisher, clock=lambda: clock_now)

    payload = SessionCreatePayload(
        start_url="https://example.test",
        headless=False,
        proxy=SessionProxySettings(http="http://proxy.example:3128"),
        metadata={"flow": "smoke"},
    )

    session = await manager.create_session(payload)

    assert session.runner_id == "runner-test"
    assert session.proxy is not None
    assert session.vnc is not None
    assert session.vnc.token is None
    assert session.vnc.token_ttl_seconds is None
    assert str(session.vnc.http_url).endswith(str(session.id))
    events = await publisher.drain()
    assert len(events) == 1
    assert events[0].type is SessionEventType.CREATED
    assert events[0].session.id == session.id
    assert events[0].occurred_at == clock_now


@pytest.mark.anyio("asyncio")
async def test_update_session_merges_labels_and_publishes_update() -> None:
    """Updates should merge labels and emit ``session.updated`` events."""

    clock_now = datetime(2024, 2, 2, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        RunnerSettings(runner_id="runner-test", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=lambda: clock_now,
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
async def test_create_session_strips_user_vnc_token() -> None:
    """User-supplied VNC tokens must be removed before persisting sessions."""

    clock_now = datetime(2024, 4, 4, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        RunnerSettings(
            runner_id="runner-token", camoufox_path="/usr/bin/camoufox"
        ),
        publisher,
        clock=lambda: clock_now,
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
async def test_update_session_strips_user_vnc_token() -> None:
    """Updates attempting to inject VNC tokens are sanitised."""

    clock_now = datetime(2024, 5, 5, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        RunnerSettings(
            runner_id="runner-update", camoufox_path="/usr/bin/camoufox"
        ),
        publisher,
        clock=lambda: clock_now,
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
async def test_end_session_sets_terminal_state_and_event() -> None:
    """``end_session`` should mark the session as DEAD and send ENDED event."""

    clock_now = datetime(2024, 3, 3, 12, 0, 0, tzinfo=UTC)
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        RunnerSettings(runner_id="runner-test", camoufox_path="/usr/bin/camoufox"),
        publisher,
        clock=lambda: clock_now,
    )
    session = await manager.create_session(SessionCreatePayload())

    ended = await manager.end_session(session.id, reason="completed")

    assert ended.status is SessionStatus.DEAD
    assert ended.ended_at == clock_now
    events = await publisher.drain()
    assert [event.type for event in events] == [SessionEventType.CREATED, SessionEventType.ENDED]
    assert events[-1].reason == "completed"


@pytest.mark.anyio("asyncio")
async def test_metrics_track_active_sessions_and_prewarm_failures() -> None:
    """Metrics should reflect active sessions and retain bounded prewarm errors."""

    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(
        RunnerSettings(
            runner_id="runner-metrics",
            camoufox_path="/usr/bin/camoufox",
            slot_limit=3,
            prewarm_failure_history_size=2,
        ),
        publisher,
    )

    first = await manager.create_session(SessionCreatePayload())
    await manager.create_session(SessionCreatePayload())
    await manager.record_prewarm_failure("warmup-1")
    await manager.record_prewarm_failure("warmup-2")
    metrics = await manager.get_metrics()

    assert metrics.active_sessions == 2
    assert metrics.prewarm_failure_count == 2
    assert metrics.prewarm_failures == ["warmup-1", "warmup-2"]
    assert metrics.last_prewarm_error == "warmup-2"

    await manager.record_prewarm_failure("warmup-3")
    metrics = await manager.get_metrics()
    assert metrics.prewarm_failures == ["warmup-2", "warmup-3"]

    await manager.end_session(first.id)
    metrics = await manager.get_metrics()
    assert metrics.active_sessions == 1
