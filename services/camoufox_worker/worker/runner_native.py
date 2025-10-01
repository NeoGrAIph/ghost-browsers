"""Native Camoufox execution helpers for worker jobs."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Optional

from camoufox.errors import CamoufoxError
from camoufox.sync_api import Camoufox

from .jobs import Job, JobError, JobMetrics, JobResult, JobStatus


def run_job(job: Job) -> JobResult:
    """Execute a job inside the current container using Camoufox directly.

    Parameters
    ----------
    job: Job
        Экземпляр задачи, описывающий URL, прокси и таймаут.

    Returns
    -------
    JobResult
        Структурированное описание выполнения: статус, таймстемпы и метрики.

    Notes
    -----
    Прокси-настройки пока не применяются; модуль выступает заглушкой для будущей интеграции
    с изолированными контекстами и сетевыми профилями.

    Examples
    --------
    >>> run_job(Job(url="https://example.com"))
    JobResult(ok=True, status=<JobStatus.SUCCESS: 'success'>, ...)
    """
    headless = os.getenv("CAMOUFOX_HEADLESS", "virtual")
    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    title: Optional[str] = None
    error: Optional[JobError] = None
    status = JobStatus.SUCCESS

    try:
        with Camoufox(headless=headless, geoip=True) as browser:
            page = browser.new_page()
            # TODO: применить прокси к браузеру/контексту, если указано в job
            page.goto(str(job.url))
            title = page.title()
    except CamoufoxError as exc:  # pragma: no cover - defensive branch for runtime errors
        status = JobStatus.FAILURE
        error = JobError(type=exc.__class__.__name__, message=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected runtime failures
        status = JobStatus.FAILURE
        error = JobError(type=exc.__class__.__name__, message=str(exc))

    finished_at = datetime.now(UTC)
    duration_ms = (time.perf_counter() - started_perf) * 1000
    metrics = JobMetrics(duration_ms=duration_ms)
    return JobResult(
        job=job,
        status=status,
        ok=status is JobStatus.SUCCESS,
        started_at=started_at,
        finished_at=finished_at,
        metrics=metrics,
        title=title,
        error=error,
    )
