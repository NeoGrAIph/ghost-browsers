"""Stress tests for the in-memory session event bridge throughput."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from statistics import mean
from uuid import UUID, uuid4

import anyio
import pytest
from core import InMemorySessionEventBridge, Session, SessionEvent, SessionEventType, SessionStatus

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """Limit stress tests to the asyncio backend."""

    return "asyncio"


def _build_ready_session() -> Session:
    """Return a ready session snapshot for stress scenarios."""

    now = datetime.now(tz=timezone.utc)
    return Session(
        id=uuid4(),
        runner_id="runner-stress",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )


async def test_inmemory_bridge_handles_thousands_of_events(
    record_property: Callable[[str, object], None],
) -> None:
    """Ensure the bridge delivers thousands of events with low latency."""

    bridge = InMemorySessionEventBridge()
    session = _build_ready_session()
    total_events = 5_000

    send_times: dict[UUID, float] = {}
    latencies: list[float] = []
    orphaned: list[UUID] = []
    completion = anyio.Event()

    async def consume() -> None:
        """Collect events from the bridge and track delivery latency."""

        stream = await bridge.subscribe()
        try:
            for _ in range(total_events):
                event = await stream.__anext__()
                arrival = anyio.current_time()
                sent_at = send_times.pop(event.id, None)
                if sent_at is None:
                    orphaned.append(event.id)
                    continue
                latencies.append(arrival - sent_at)
            completion.set()
        finally:
            await stream.aclose()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(consume)
        await anyio.sleep(0)

        publish_started_at = anyio.current_time()
        for _ in range(total_events):
            event = SessionEvent(
                session=session,
                occurred_at=datetime.now(tz=timezone.utc),
                type=SessionEventType.UPDATED,
            )
            send_times[event.id] = anyio.current_time()
            await bridge.publish(event)
        publish_duration = anyio.current_time() - publish_started_at

        await completion.wait()
        task_group.cancel_scope.cancel()

    assert not send_times, "All published events should be observed by subscribers."
    assert not orphaned, f"Subscriber received unexpected events: {orphaned!r}"
    assert len(latencies) == total_events, "Every event should record a latency measurement."

    average_latency = mean(latencies)
    peak_latency = max(latencies)

    record_property("bridge_publish_duration_ms", publish_duration * 1_000)
    record_property("bridge_average_latency_ms", average_latency * 1_000)
    record_property("bridge_peak_latency_ms", peak_latency * 1_000)

    assert average_latency <= 0.06, f"Average latency too high: {average_latency:.6f}s"
    assert peak_latency <= 0.25, f"Peak latency too high: {peak_latency:.6f}s"
    assert publish_duration <= 2.5, f"Publishing took too long: {publish_duration:.6f}s"
