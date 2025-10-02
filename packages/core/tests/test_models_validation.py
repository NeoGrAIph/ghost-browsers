"""Regression tests covering core model validation rules."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from pydantic import ValidationError

from core.models import (
    Runner,
    RunnerState,
    Session,
    SessionEvent,
    SessionEventType,
    SessionProxySettings,
    SessionStatus,
    SessionVncDetails,
    WorkstationEvent,
    WorkstationEventType,
    WorkstationMeta,
    WorkstationState,
)


def _build_session(status: SessionStatus = SessionStatus.INIT) -> Session:
    """Create a minimal session snapshot for validation-focused tests."""

    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        runner_id="runner-1",
        status=status,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )


def _build_workstation_meta(
    *,
    workstation_id: str = "ws-1",
    fingerprint_id: str = "fp-1",
    state: WorkstationState = WorkstationState.AVAILABLE,
) -> WorkstationMeta:
    """Return workstation metadata for validation tests."""

    return WorkstationMeta(id=workstation_id, fingerprint_id=fingerprint_id, state=state)


def test_session_proxy_settings_requires_at_least_one_url() -> None:
    """Reject proxy settings that omit all supported proxy endpoints."""

    with pytest.raises(ValidationError):
        SessionProxySettings()

    config = SessionProxySettings(http="http://proxy.local:8080")
    assert config.http.host == "proxy.local"


def test_session_vnc_details_requires_url_and_limits_token_ttl() -> None:
    """Enforce URL presence, TTL bounds and token dependencies for VNC payloads."""

    with pytest.raises(ValidationError):
        SessionVncDetails(token="opaque", token_ttl_seconds=60)

    with pytest.raises(ValidationError):
        SessionVncDetails(websocket_url="wss://vnc/ws", token="opaque")

    with pytest.raises(ValidationError):
        SessionVncDetails(websocket_url="wss://vnc/ws", token="opaque", token_ttl_seconds=3601)

    details = SessionVncDetails(websocket_url="wss://vnc/ws")
    assert details.websocket_url.host == "vnc"


def test_runner_derives_available_slots_and_validates_constraints() -> None:
    """Ensure Runner defaults derived values and rejects inconsistent states."""

    runner = Runner(id=" runner-42 ", base_url="http://runner:9000", total_slots=4)
    assert runner.available_slots == 4
    assert runner.id == "runner-42"

    with pytest.raises(ValidationError):
        Runner(id="runner-1", base_url="http://runner", total_slots=1, available_slots=2)

    with pytest.raises(ValidationError):
        Runner(
            id="runner-1",
            base_url="http://runner",
            total_slots=1,
            available_slots=0,
            state=RunnerState.OFFLINE,
            healthy=True,
        )


def test_session_event_requires_timezone_and_status_alignment() -> None:
    """Validate timezone awareness and status/type relationships for events."""

    session = _build_session(status=SessionStatus.READY)
    occurred_at = datetime.now(UTC)
    event = SessionEvent(session=session, occurred_at=occurred_at)
    assert event.runner_id == "runner-1"
    assert event.is_terminal is False

    with pytest.raises(ValidationError):
        SessionEvent(session=session, occurred_at=datetime.now(), type=SessionEventType.CREATED)

    with pytest.raises(ValidationError):
        SessionEvent(
            session=_build_session(status=SessionStatus.DEAD),
            occurred_at=occurred_at,
            type=SessionEventType.CREATED,
        )

    with pytest.raises(ValidationError):
        SessionEvent(
            session=_build_session(status=SessionStatus.READY),
            occurred_at=occurred_at,
            type=SessionEventType.ENDED,
        )

    terminal_event = SessionEvent(
        session=_build_session(status=SessionStatus.DEAD),
        occurred_at=occurred_at,
        type=SessionEventType.ENDED,
    )
    assert terminal_event.is_terminal is True


def test_session_accepts_missing_workstation_fields_for_compatibility() -> None:
    """Legacy payloads without workstation data remain valid."""

    session = _build_session()
    assert session.workstation is None
    assert session.workstation_id is None


def test_session_rejects_mismatched_workstation_metadata() -> None:
    """Session validation fails when workstation identifiers are inconsistent."""

    with pytest.raises(ValidationError):
        Session(
            id=uuid4(),
            runner_id="runner-1",
            status=SessionStatus.INIT,
            created_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            headless=False,
            idle_ttl_seconds=300,
            workstation_id="ws-expected",
            workstation=_build_workstation_meta(workstation_id="ws-other"),
        )


def test_workstation_event_requires_timezone_and_trims_reason() -> None:
    """Workstation events require timezone-aware timestamps and clean reasons."""

    meta = _build_workstation_meta()
    occurred_at = datetime.now(UTC)
    event = WorkstationEvent(
        workstation=meta,
        occurred_at=occurred_at,
        type=WorkstationEventType.RELEASED,
        reason="  maintenance  ",
    )
    assert event.reason == "maintenance"

    with pytest.raises(ValidationError):
        WorkstationEvent(workstation=meta, occurred_at=datetime.now())
