"""Data models describing executable Camoufox jobs for the worker service."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


class Job(BaseModel):
    """Describe a single browser automation task to be executed by the worker.

    Parameters
    ----------
    url: HttpUrl
        Полностью квалифицированный URL, который необходимо открыть в браузере.
    http_proxy: str | None
        Необязательный HTTP-прокси для текущей задачи в формате схемы URL.
    https_proxy: str | None
        Необязательный HTTPS-прокси; если не указан, можно использовать `http_proxy`.
    socks_proxy: str | None
        Необязательный SOCKS-прокси (например, `socks5://user:pass@host:port`).
    timeout_sec: int
        Предельное время выполнения задачи в секундах; по умолчанию 60.

    Returns
    -------
    Job
        Pydantic-модель с валидацией входных данных и приведением типов.

    Examples
    --------
    >>> Job(url="https://example.com", timeout_sec=120)
    Job(url=HttpUrl('https://example.com', ...), timeout_sec=120)
    """

    url: HttpUrl
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    socks_proxy: Optional[str] = None
    timeout_sec: int = 60


class JobStatus(str, Enum):
    """Enumerate the high-level result of executing a worker job."""

    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"


class JobError(BaseModel):
    """Describe an unrecoverable error encountered during job execution.

    Attributes
    ----------
    type: str
        Человекочитаемое или программное имя класса исключения.
    message: str
        Сообщение ошибки, возвращённое рантаймом/движком.
    details: str | None
        Необязательное поле для трассировки или дополнительного контекста.
    """

    type: str
    message: str
    details: Optional[str] = None


class JobMetrics(BaseModel):
    """Execution metrics captured for a worker job run.

    Attributes
    ----------
    duration_ms: float
        Полное время выполнения задачи, включая прогрев браузера и навигацию.
    extra: dict[str, float]
        Дополнительные числовые показатели (сетевые задержки, размер артефактов и т.п.).
    """

    duration_ms: float = Field(..., ge=0, description="Полное время выполнения задачи в миллисекундах.")
    extra: Dict[str, float] = Field(
        default_factory=dict,
        description="Произвольные числовые метрики (например, сетевые задержки).",
    )


class JobResult(BaseModel):
    """Structured representation of the outcome of a worker job.

    Attributes
    ----------
    job: Job
        Оригинальная задача, чтобы потребители могли сопоставлять результаты с входами.
    status: JobStatus
        Итоговое состояние выполнения (`success`, `failure` или `aborted`).
    ok: bool
        Булев флаг, отражающий успешность выполнения (true, когда `status == success`).
    started_at: datetime
        Таймстемп запуска в UTC.
    finished_at: datetime
        Таймстемп завершения в UTC.
    metrics: JobMetrics
        Собранные метрики выполнения.
    title: str | None
        Пример артефакта нативного раннера (заголовок страницы после перехода).
    error: JobError | None
        Детали ошибки, если задача завершилась неуспешно.
    """

    job: Job
    status: JobStatus
    ok: bool
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime
    metrics: JobMetrics
    title: Optional[str] = None
    error: Optional[JobError] = None

    @model_validator(mode="after")
    def _validate_temporal_bounds(self) -> "JobResult":
        """Ensure timestamps are ordered and success status matches the ok flag."""

        if self.finished_at < self.started_at:
            raise ValueError("finished_at must be greater than or equal to started_at")
        expected_ok = self.status is JobStatus.SUCCESS
        if self.ok != expected_ok:
            raise ValueError("ok must reflect whether the status equals success")
        return self
