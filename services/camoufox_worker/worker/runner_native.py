"""Native Camoufox execution helpers for worker jobs."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from camoufox.errors import CamoufoxError
from camoufox.sync_api import Camoufox

from .jobs import Job, JobError, JobMetrics, JobResult, JobStatus


def _build_proxy_options(job: Job) -> Dict[str, Any]:
    """Return Camoufox context options derived from the job proxy settings.

    Parameters
    ----------
    job:
        Задача, содержащая необязательные строки подключения к прокси.

    Returns
    -------
    dict[str, Any]
        Набор аргументов для ``browser.new_context`` или ``browser.new_page``.
        Если прокси не указан, возвращается пустой словарь.

    Notes
    -----
    Приоритет отдается SOCKS, затем HTTPS и HTTP прокси — это соответствует
    способу, которым Playwright принимает единственный сервер в
    ``proxy.server``.

    Examples
    --------
    >>> job = Job(url="https://example.com", http_proxy="http://user:pwd@localhost:8080")
    >>> options = _build_proxy_options(job)
    >>> options["proxy"]["server"]
    'http://localhost:8080'
    """

    proxy_url = job.socks_proxy or job.https_proxy or job.http_proxy
    if not proxy_url:
        return {}

    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid proxy URL: {proxy_url}")

    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server = f"{server}:{parsed.port}"

    proxy: Dict[str, Any] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password

    return {"proxy": proxy}


def run_job(job: Job) -> JobResult:
    """Execute a job inside the current container using Camoufox directly.

    Parameters
    ----------
    job:
        Экземпляр задачи, описывающий URL, прокси и таймаут.

    Returns
    -------
    JobResult
        Структурированное описание выполнения: статус, таймстемпы и метрики.

    Notes
    -----
    Функция применяет прокси-опции к новому контексту Camoufox и гарантирует,
    что переход выполняется с таймаутом ``job.timeout_sec``. Контекст и
    страница закрываются даже при ошибках навигации.

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
    navigation_status = "not_attempted"
    navigation_duration_ms: Optional[float] = None
    exception_type: Optional[str] = None
    context_obj: Any = None
    page_obj: Any = None
    timeout_ms = int(job.timeout_sec * 1000)

    try:
        with Camoufox(headless=headless, geoip=True) as browser:
            proxy_options = _build_proxy_options(job)

            try:
                if hasattr(browser, "new_context"):
                    context_obj = browser.new_context(**proxy_options)
                    page_obj = context_obj.new_page()
                else:
                    page_obj = browser.new_page(**proxy_options)
            except Exception:
                navigation_status = "context_failed"
                raise

            try:
                navigation_started = time.perf_counter()
                page_obj.goto(job.url_source, timeout=timeout_ms)
            except Exception:
                navigation_status = "navigation_failed"
                raise
            else:
                navigation_status = "success"
                navigation_duration_ms = (time.perf_counter() - navigation_started) * 1000
                title = page_obj.title()
    except CamoufoxError as exc:  # pragma: no cover - defensive branch for runtime errors
        status = JobStatus.FAILURE
        if navigation_status == "not_attempted":
            navigation_status = "context_failed"
        error = JobError(type=exc.__class__.__name__, message=str(exc))
        exception_type = exc.__class__.__name__
    except Exception as exc:  # pragma: no cover - unexpected runtime failures
        status = JobStatus.FAILURE
        if navigation_status == "not_attempted":
            navigation_status = "context_failed"
        error = JobError(type=exc.__class__.__name__, message=str(exc))
        exception_type = exc.__class__.__name__
    finally:
        for closable in (page_obj, context_obj):
            close = getattr(closable, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover - defensive close cleanup
                    pass

    finished_at = datetime.now(UTC)
    duration_ms = (time.perf_counter() - started_perf) * 1000
    metrics = JobMetrics(
        duration_ms=duration_ms,
        extra={
            "navigation_status": navigation_status,
            "navigation_duration_ms": navigation_duration_ms or 0.0,
            "timeout_ms": float(timeout_ms),
        },
    )

    if exception_type:
        metrics.extra["exception_type"] = exception_type

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
