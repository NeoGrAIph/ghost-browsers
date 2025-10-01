"""Data models describing executable Camoufox jobs for the worker service."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

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
    url_source: str
        Исходная строка URL, сохранённая для навигации без автоматического добавления слэшей.

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
    url_source: str = Field(
        default="",
        exclude=True,
        repr=False,
        description="Исходная строка URL до нормализации Pydantic.",
    )

    @model_validator(mode="before")
    @classmethod
    def _capture_original_url(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Сохранить исходную строку URL до валидации HttpUrl."""

        raw_url = data.get("url")
        if isinstance(raw_url, str) and not data.get("url_source"):
            data["url_source"] = raw_url
        return data

    @model_validator(mode="after")
    def _ensure_original_url(self) -> "Job":
        """Гарантировать наличие исходной строки URL после нормализации."""

        if not self.url_source:
            self.url_source = str(self.url)
        return self


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


MetricValue = Union[float, int, str, bool, None]


class JobMetrics(BaseModel):
    """Execution metrics captured for a worker job run.

    Attributes
    ----------
    duration_ms: float
        Полное время выполнения задачи, включая прогрев браузера и навигацию.
    extra: dict[str, MetricValue]
        Дополнительные показатели (сетевые задержки, коды статуса, флаги таймаутов и т.п.).
    """

    duration_ms: float = Field(
        ..., ge=0, description="Полное время выполнения задачи (мс)."
    )
    extra: Dict[str, MetricValue] = Field(
        default_factory=dict,
        description="Произвольные метрики (например, задержки, статусы навигации, флаги ошибок).",
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
