"""Stress tests for the in-memory session event publisher."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from statistics import mean
from uuid import uuid4

import anyio
import pytest
from app.events import InMemorySessionEventPublisher
from core import Session, SessionEvent, SessionStatus


def _build_ready_session() -> Session:
    """Produce a ready session snapshot for publisher benchmarks."""

    now = datetime.now(tz=timezone.utc)
    return Session(
        id=uuid4(),
        runner_id="runner-publisher",
        status=SessionStatus.READY,
        created_at=now,
        last_seen_at=now,
        headless=False,
        idle_ttl_seconds=300,
    )


@pytest.mark.anyio("asyncio")
async def test_inmemory_publisher_drain_latency_under_parallel_load(
    record_property: Callable[[str, object], None],
) -> None:
    """Publish events in parallel and verify ``drain`` latency remains low."""

    publisher = InMemorySessionEventPublisher()
    session = _build_ready_session()
    concurrent_publishers = 10
    events_per_publisher = 1_000
    total_events = concurrent_publishers * events_per_publisher

    publish_latencies: list[float] = []

    async def publish_batch() -> None:
        """Push a batch of events via the shared publisher."""

        for _ in range(events_per_publisher):
            event = SessionEvent(
                session=session,
                occurred_at=datetime.now(tz=timezone.utc),
            )
            started_at = anyio.current_time()
            await publisher.publish(event)
            publish_latencies.append(anyio.current_time() - started_at)

    async with anyio.create_task_group() as task_group:
        for _ in range(concurrent_publishers):
            task_group.start_soon(publish_batch)

    drain_started_at = anyio.current_time()
    drained = await publisher.drain()
    drain_duration = anyio.current_time() - drain_started_at

    record_property("publisher_total_events", len(drained))
    record_property("publisher_drain_duration_ms", drain_duration * 1_000)

    assert len(drained) == total_events, "Drain should return every published event."
    assert len(publish_latencies) == total_events, "Each publish call should capture latency."

    average_publish_latency = mean(publish_latencies)
    peak_publish_latency = max(publish_latencies)

    record_property("publisher_average_publish_latency_ms", average_publish_latency * 1_000)
    record_property("publisher_peak_publish_latency_ms", peak_publish_latency * 1_000)

    assert drain_duration <= 0.2, (
        f"Drain took too long ({drain_duration:.6f}s) for {total_events} events",
    )
    assert average_publish_latency <= 0.02, (
        f"Average publish latency is too high: {average_publish_latency:.6f}s",
    )
    assert peak_publish_latency <= 0.1, (
        f"Peak publish latency is too high: {peak_publish_latency:.6f}s",
    )

    drained_after_cleanup = await publisher.drain()
    assert not drained_after_cleanup, "Subsequent drain should be empty after cleanup."
