"""Unit tests covering worker job request and result models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from worker.jobs import Job, JobError, JobMetrics, JobResult, JobStatus


def test_job_validates_url_and_defaults() -> None:
    """Ensure Job enforces URL validation and default timeout."""

    job = Job(url="https://example.com")
    assert job.timeout_sec == 60

    with pytest.raises(ValidationError):
        Job(url="not-a-valid-url")


def test_job_metrics_require_non_negative_duration() -> None:
    """Reject metrics where execution duration is negative."""

    with pytest.raises(ValidationError):
        JobMetrics(duration_ms=-1)


def test_job_result_enforces_temporal_order_and_ok_flag() -> None:
    """Ensure JobResult validates timestamp ordering and ok flag consistency."""

    job = Job(url="https://example.com")
    started = datetime.now(UTC)
    finished = started + timedelta(seconds=1)
    result = JobResult(
        job=job,
        status=JobStatus.SUCCESS,
        ok=True,
        started_at=started,
        finished_at=finished,
        metrics=JobMetrics(duration_ms=1000),
        title="Example Domain",
    )
    assert result.ok is True

    with pytest.raises(ValidationError):
        JobResult(
            job=job,
            status=JobStatus.SUCCESS,
            ok=False,
            started_at=started,
            finished_at=finished,
            metrics=JobMetrics(duration_ms=1000),
        )

    with pytest.raises(ValidationError):
        JobResult(
            job=job,
            status=JobStatus.FAILURE,
            ok=True,
            started_at=finished,
            finished_at=started,
            metrics=JobMetrics(duration_ms=1000),
            error=JobError(type="Boom", message="failure"),
        )
