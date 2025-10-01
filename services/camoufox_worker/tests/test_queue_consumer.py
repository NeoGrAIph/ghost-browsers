"""Integration tests for the queue consumer and in-memory backend."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worker.jobs import Job, JobMetrics, JobResult, JobStatus
from worker.queue import (
    JOB_DROPS,
    JOB_EXECUTIONS,
    JOB_RETRIES,
    QUEUE_DEPTH,
    InMemoryQueueBackend,
    JobQueueConsumer,
    JobQueueMessage,
)


def _success_result(job: Job) -> JobResult:
    """Helper returning a successful :class:`JobResult`."""

    now = datetime.now(UTC)
    return JobResult(
        job=job,
        status=JobStatus.SUCCESS,
        ok=True,
        started_at=now,
        finished_at=now,
        metrics=JobMetrics(duration_ms=10.0),
    )


@pytest.fixture
def anyio_backend() -> str:
    """Force AnyIO to use the asyncio backend for this module."""

    return "asyncio"


@pytest.mark.anyio("asyncio")
async def test_consumer_processes_job_and_updates_metrics() -> None:
    """The consumer should execute a native job and update Prometheus metrics."""

    backend = InMemoryQueueBackend()
    job = Job(url="https://example.com")
    await backend.enqueue(
        JobQueueMessage(
            job=job,
            mode="native",
            profile_toggles={"headless": "virtual"},
        )
    )

    env_values: dict[str, str] = {}

    async def native_executor(job: Job, toggles, metadata):  # type: ignore[override]
        # Capture applied toggles from environment for assertions.
        env_values.update({key: value for key, value in toggles.items()})
        return _success_result(job)

    orchestrator_executor = native_executor
    consumer = JobQueueConsumer(
        backend,
        native_executor=native_executor,
        orchestrator_executor=orchestrator_executor,
        default_profile_toggles={"trace": "0"},
    )

    success_counter = JOB_EXECUTIONS.labels("native", JobStatus.SUCCESS.value)
    start_value = success_counter._value.get()  # type: ignore[attr-defined]

    await consumer.poll_once()

    assert env_values == {"trace": "0", "headless": "virtual"}
    assert success_counter._value.get() == start_value + 1  # type: ignore[attr-defined]
    assert QUEUE_DEPTH.labels("memory")._value.get() == 0  # type: ignore[attr-defined]


@pytest.mark.anyio("asyncio")
async def test_consumer_retries_and_finally_drops() -> None:
    """Failures should trigger retries until the limit, then drop the job."""

    backend = InMemoryQueueBackend()
    job = Job(url="https://retry.example")
    await backend.enqueue(JobQueueMessage(job=job, max_attempts=2))

    attempts: list[int] = []

    async def native_executor(job: Job, toggles, metadata):  # type: ignore[override]
        attempts.append(len(attempts) + 1)
        raise RuntimeError("boom")

    consumer = JobQueueConsumer(
        backend,
        native_executor=native_executor,
        orchestrator_executor=native_executor,
    )

    retries_counter = JOB_RETRIES.labels("native")
    start_retries = retries_counter._value.get()  # type: ignore[attr-defined]
    drops_counter = JOB_DROPS.labels("native", "max_attempts")
    start_drops = drops_counter._value.get()  # type: ignore[attr-defined]

    await consumer.poll_once()  # attempt 1 -> retry
    await consumer.poll_once()  # attempt 2 -> drop

    assert attempts == [1, 2]
    assert retries_counter._value.get() == start_retries + 1  # type: ignore[attr-defined]
    assert drops_counter._value.get() == start_drops + 1  # type: ignore[attr-defined]


@pytest.mark.anyio("asyncio")
async def test_idempotency_skips_duplicate_messages() -> None:
    """When the idempotency key is repeated the second message is skipped."""

    backend = InMemoryQueueBackend()
    job = Job(url="https://idempotent.example")
    message = JobQueueMessage(job=job, idempotency_key="abc")
    await backend.enqueue(message)

    executions: list[Job] = []

    async def native_executor(job: Job, toggles, metadata):  # type: ignore[override]
        executions.append(job)
        return _success_result(job)

    consumer = JobQueueConsumer(
        backend,
        native_executor=native_executor,
        orchestrator_executor=native_executor,
    )

    await consumer.poll_once()
    await backend.enqueue(message)
    await consumer.poll_once()

    assert len(executions) == 1
