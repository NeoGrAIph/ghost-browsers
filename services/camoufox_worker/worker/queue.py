"""Utilities for consuming queued Camoufox jobs and dispatching executors.

This module provides an extensible job consumer that is capable of pulling
messages from heterogeneous transports (Redis streams, AMQP queues, or
in-memory backends used for testing). Each message is validated via Pydantic
and dispatched to either the native or orchestrator executor depending on the
requested mode. The consumer instruments the execution lifecycle with
Prometheus metrics and structured JSON logging, tracks retry attempts, and
implements basic idempotency semantics to avoid re-processing already
completed jobs.

Typical usage
-------------
```
>>> backend = InMemoryQueueBackend()
>>> consumer = JobQueueConsumer(backend, native_executor=run_native)
>>> await backend.enqueue(JobQueueMessage(job=Job(url="https://example.com")))
>>> await consumer.poll_once()
```

The :class:`JobQueueConsumer` class is transport agnostic; applications are
expected to provide an implementation of :class:`QueueBackendProtocol` that
knows how to ``receive``/``ack``/``requeue`` messages for the specific queue
technology in use. Redis and AMQP adapters are provided for reference and can
be extended further when real infrastructure is available.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Dict, Mapping, MutableMapping, Optional, Protocol

from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field, field_validator

import anyio

from .jobs import Job, JobResult, JobStatus
from .runner_native import run_job as run_native_job
from .runner_orch import create_gateway_client, run_orchestrated_job

logger = logging.getLogger(__name__)


# Prometheus metrics used by the consumer. Labels are intentionally scoped to
# low-cardinality attributes (mode/backend/status) to avoid unbounded metric
# growth when operating under high concurrency.
JOB_EXECUTIONS = Counter(
    "camoufox_worker_job_executions_total",
    "Total number of job execution attempts.",
    labelnames=("mode", "status"),
)
JOB_RETRIES = Counter(
    "camoufox_worker_job_retries_total",
    "Count of jobs requeued for another attempt.",
    labelnames=("mode",),
)
JOB_DROPS = Counter(
    "camoufox_worker_job_drops_total",
    "Number of jobs permanently dropped after exhausting retries.",
    labelnames=("mode", "reason"),
)
JOB_DURATION = Histogram(
    "camoufox_worker_job_duration_seconds",
    "Observed wall-clock duration of job executions.",
    labelnames=("mode", "status"),
)
QUEUE_DEPTH = Gauge(
    "camoufox_worker_queue_depth",
    "Approximate depth of the upstream queue.",
    labelnames=("backend",),
)


def _serialize_for_log(value: Any) -> Any:
    """Convert unsupported values into JSON-friendly representations."""

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


def _log_event(event: str, **fields: Any) -> None:
    """Emit structured JSON log events with consistent naming.

    Parameters
    ----------
    event:
        Logical event name (``job_received``, ``job_completed``, etc.).
    **fields:
        Дополнительные атрибуты, сериализуемые в JSON. Значения
        автоматически преобразуются в человекочитаемый формат (например,
        временные метки → ISO8601).

    Side Effects
    ------------
    Пишет строку JSON в стандартный обработчик логгера ``__name__``. Это
    обеспечивает структурированное логирование без необходимости внешних
    библиотек вроде ``structlog``.
    """

    payload = {"event": event}
    for key, value in fields.items():
        payload[key] = _serialize_for_log(value)
    logger.info(json.dumps(payload, ensure_ascii=False))


def parse_profile_toggles(raw: str | None) -> dict[str, str]:
    """Parse a comma-separated list of ``key=value`` profile toggles.

    Parameters
    ----------
    raw:
        Строка в формате ``key=value,key2=value2``. Пробелы вокруг ключей и
        значений игнорируются. Значения по умолчанию приводятся к строкам, что
        упрощает передачу в переменные окружения.

    Returns
    -------
    dict[str, str]
        Словарь ``{ключ: значение}`` для использования в задачах.

    Examples
    --------
    >>> parse_profile_toggles("headless=virtual,trace=1")
    {'headless': 'virtual', 'trace': '1'}
    """

    toggles: dict[str, str] = {}
    if not raw:
        return toggles
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip()
        value = value.strip() if value else "1"
        if key:
            toggles[key] = value
    return toggles


@contextlib.contextmanager
def apply_profile_toggles(toggles: Mapping[str, Any]) -> None:
    """Temporarily apply profile toggles as environment variables.

    Каждый флаг маппится на переменную окружения ``CAMOUFOX_TUMBLER_<KEY>``.
    Это простой механизм для включения/выключения возможностей раннера
    (например, трассировка, особые user-agent профили). После завершения
    контекста переменные откатываются к исходным значениям.

    Parameters
    ----------
    toggles:
        Словарь тумблеров. Ключи нормализуются в верхний регистр.
    """

    normalized: dict[str, str] = {
        f"CAMOUFOX_TUMBLER_{key.upper()}": str(value) for key, value in toggles.items()
    }
    previous: dict[str, Optional[str]] = {
        env_key: os.environ.get(env_key) for env_key in normalized.keys()
    }
    try:
        os.environ.update(normalized)
        yield
    finally:
        for env_key, original in previous.items():
            if original is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = original


def load_default_profile_toggles(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Load profile toggles from ``WORKER_PROFILE_TOGGLES`` in ``env``."""

    env = env or os.environ
    return parse_profile_toggles(env.get("WORKER_PROFILE_TOGGLES"))


class JobQueueMessage(BaseModel):
    """Envelope describing a job pulled from a message queue.

    Attributes
    ----------
    job:
        Экземпляр :class:`worker.jobs.Job`, описывающий браузерную задачу.
    mode:
        Режим выполнения. Допустимые значения: ``native`` или ``orchestrator``.
    max_attempts:
        Максимальное число попыток перед окончательным отказом.
    idempotency_key:
        Опциональный ключ идемпотентности. Повторные сообщения с тем же ключом
        не будут обработаны повторно после успешного завершения.
    idempotency_ttl_sec:
        Время жизни записи об идемпотентности (секунды). По умолчанию 10 минут.
    metadata:
        Дополнительные данные очереди/отправителя. Используются, например, для
        передачи параметров оркестратора.
    profile_toggles:
        Набор тумблеров (флагов профиля), которые применяются в контексте
        выполнения задачи.
    """

    job: Job
    mode: str = Field(default="native")
    max_attempts: int = Field(default=3, ge=1)
    idempotency_key: Optional[str] = None
    idempotency_ttl_sec: int = Field(default=600, ge=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    profile_toggles: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def _normalize_mode(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"native", "orchestrator"}:
            raise ValueError("mode must be 'native' or 'orchestrator'")
        return normalized


@dataclass(slots=True)
class JobQueueEnvelope:
    """Container object returned by queue backends.

    Parameters
    ----------
    delivery_tag:
        Уникальный идентификатор доставки (используется бекендом для ack/nack).
    message:
        Содержимое очереди (см. :class:`JobQueueMessage`).
    attempt:
        Номер текущей попытки (начинается с 1).
    available_at:
        Таймстемп, когда сообщение стало доступным потребителю.
    """

    delivery_tag: str
    message: JobQueueMessage
    attempt: int = 1
    available_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class QueueBackendProtocol(Protocol):
    """Protocol for queue backends consumed by :class:`JobQueueConsumer`."""

    name: str

    async def receive(self, *, timeout: float | None = None) -> JobQueueEnvelope | None:
        """Fetch a message from the queue or return ``None`` if timed out."""

    async def ack(self, envelope: JobQueueEnvelope) -> None:
        """Acknowledge successful processing of ``envelope``."""

    async def requeue(self, envelope: JobQueueEnvelope, *, delay: float | None = None) -> None:
        """Return the message back to the queue for another attempt."""

    async def reject(self, envelope: JobQueueEnvelope) -> None:
        """Drop the message permanently without requeueing."""

    async def depth(self) -> int:
        """Return an approximate queue depth for instrumentation."""


class IdempotencyRegistry:
    """In-memory registry that tracks completed idempotency keys."""

    def __init__(self, *, default_ttl: float = 600.0) -> None:
        self._default_ttl = default_ttl
        self._records: MutableMapping[str, float] = {}

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [key for key, expires_at in self._records.items() if expires_at <= now]
        for key in expired:
            self._records.pop(key, None)

    def is_completed(self, key: str) -> bool:
        """Check whether ``key`` has already completed successfully."""

        self._purge()
        return key in self._records

    def mark_completed(self, key: str, *, ttl: float | None = None) -> None:
        """Mark ``key`` as completed for ``ttl`` seconds."""

        self._purge()
        expiration = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        self._records[key] = expiration


JobExecutor = Callable[[Job, Mapping[str, Any], Mapping[str, Any]], Awaitable[JobResult]]


class JobQueueConsumer:
    """Consume jobs from a queue backend and execute them sequentially.

    Parameters
    ----------
    backend:
        Реализация :class:`QueueBackendProtocol` (Redis, AMQP или тестовая).
    native_executor / orchestrator_executor:
        Корутины, выполняющие задачу в соответствующем режиме. Им передаётся
        ``(job, profile_toggles, metadata)``.
    receive_timeout:
        Максимальное время ожидания сообщения из очереди (секунды).
    idle_sleep:
        Пауза между попытками чтения при пустой очереди.
    default_profile_toggles:
        Тумблеры по умолчанию, например прочитанные из переменной окружения
        ``WORKER_PROFILE_TOGGLES``.
    idempotency_registry:
        Хранилище идемпотентности. По умолчанию используется in-memory
        реализация на базе :class:`IdempotencyRegistry`.
    """

    def __init__(
        self,
        backend: QueueBackendProtocol,
        *,
        native_executor: JobExecutor,
        orchestrator_executor: JobExecutor,
        receive_timeout: float = 1.0,
        idle_sleep: float = 0.1,
        default_profile_toggles: Optional[Mapping[str, Any]] = None,
        idempotency_registry: Optional[IdempotencyRegistry] = None,
    ) -> None:
        self._backend = backend
        self._native_executor = native_executor
        self._orchestrator_executor = orchestrator_executor
        self._receive_timeout = receive_timeout
        self._idle_sleep = idle_sleep
        self._default_profile_toggles = dict(default_profile_toggles or {})
        self._idempotency_registry = idempotency_registry or IdempotencyRegistry()

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        """Continuously poll the queue until ``stop_event`` is set."""

        while True:
            processed = await self.poll_once()
            if stop_event and stop_event.is_set() and not processed:
                break
            if not processed:
                await asyncio.sleep(self._idle_sleep)

    async def poll_once(self) -> bool:
        """Process a single message if available; return ``True`` on success."""

        envelope = await self._backend.receive(timeout=self._receive_timeout)
        await self._update_queue_depth()
        if envelope is None:
            return False
        message = envelope.message

        _log_event(
            "job_received",
            delivery_tag=envelope.delivery_tag,
            attempt=envelope.attempt,
            mode=message.mode,
            idempotency_key=message.idempotency_key,
        )

        if message.idempotency_key and self._idempotency_registry.is_completed(message.idempotency_key):
            _log_event(
                "job_skipped_idempotent",
                delivery_tag=envelope.delivery_tag,
                idempotency_key=message.idempotency_key,
            )
            await self._backend.ack(envelope)
            return True

        try:
            result = await self._execute_message(envelope)
        except Exception as exc:  # noqa: BLE001 - хотим логировать любые сбои
            await self._handle_failure(envelope, error=str(exc))
            return True

        if result.ok:
            await self._handle_success(envelope, result)
        else:
            await self._handle_failure(
                envelope,
                error=result.error.model_dump() if result.error else "unknown",
                result=result,
            )
        return True

    async def _execute_message(self, envelope: JobQueueEnvelope) -> JobResult:
        message = envelope.message
        toggles = {**self._default_profile_toggles, **message.profile_toggles}
        metadata = message.metadata
        executor = (
            self._native_executor if message.mode == "native" else self._orchestrator_executor
        )

        start = time.perf_counter()
        try:
            with apply_profile_toggles(toggles):
                result = await executor(message.job, toggles, metadata)
        except Exception as exc:  # noqa: BLE001
            duration = time.perf_counter() - start
            JOB_DURATION.labels(message.mode, JobStatus.FAILURE.value).observe(duration)
            JOB_EXECUTIONS.labels(message.mode, JobStatus.FAILURE.value).inc()
            _log_event(
                "job_execution_error",
                delivery_tag=envelope.delivery_tag,
                attempt=envelope.attempt,
                mode=message.mode,
                duration_ms=round(duration * 1000, 3),
                error=str(exc),
            )
            raise

        duration = time.perf_counter() - start
        JOB_DURATION.labels(message.mode, result.status.value).observe(duration)
        JOB_EXECUTIONS.labels(message.mode, result.status.value).inc()
        _log_event(
            "job_executed",
            delivery_tag=envelope.delivery_tag,
            attempt=envelope.attempt,
            mode=message.mode,
            duration_ms=round(duration * 1000, 3),
            status=result.status.value,
        )
        return result

    async def _handle_success(self, envelope: JobQueueEnvelope, result: JobResult) -> None:
        await self._backend.ack(envelope)
        message = envelope.message
        if message.idempotency_key:
            self._idempotency_registry.mark_completed(
                message.idempotency_key,
                ttl=float(message.idempotency_ttl_sec),
            )
        _log_event(
            "job_completed",
            delivery_tag=envelope.delivery_tag,
            attempt=envelope.attempt,
            mode=message.mode,
            finished_at=result.finished_at,
        )

    async def _handle_failure(
        self,
        envelope: JobQueueEnvelope,
        *,
        error: Any,
        result: JobResult | None = None,
    ) -> None:
        message = envelope.message
        if envelope.attempt >= message.max_attempts:
            await self._backend.reject(envelope)
            JOB_DROPS.labels(message.mode, "max_attempts").inc()
            _log_event(
                "job_dropped",
                delivery_tag=envelope.delivery_tag,
                attempt=envelope.attempt,
                mode=message.mode,
                error=error,
            )
            return

        JOB_RETRIES.labels(message.mode).inc()
        _log_event(
            "job_retry",
            delivery_tag=envelope.delivery_tag,
            attempt=envelope.attempt,
            mode=message.mode,
            error=error,
        )
        await self._backend.requeue(envelope)

    async def _update_queue_depth(self) -> None:
        depth = await self._backend.depth()
        QUEUE_DEPTH.labels(self._backend.name).set(depth)


class InMemoryQueueBackend:
    """Minimal in-memory queue backend primarily intended for tests."""

    def __init__(self) -> None:
        self.name = "memory"
        self._queue: list[JobQueueEnvelope] = []
        self._inflight: dict[str, JobQueueEnvelope] = {}

    async def enqueue(self, message: JobQueueMessage, *, attempt: int = 1) -> JobQueueEnvelope:
        envelope = JobQueueEnvelope(
            delivery_tag=f"msg-{len(self._queue) + len(self._inflight) + 1}",
            message=message,
            attempt=attempt,
        )
        self._queue.append(envelope)
        return envelope

    async def receive(self, *, timeout: float | None = None) -> JobQueueEnvelope | None:
        if not self._queue:
            if timeout:
                await asyncio.sleep(timeout)
            return None
        envelope = self._queue.pop(0)
        self._inflight[envelope.delivery_tag] = envelope
        return envelope

    async def ack(self, envelope: JobQueueEnvelope) -> None:
        self._inflight.pop(envelope.delivery_tag, None)

    async def requeue(self, envelope: JobQueueEnvelope, *, delay: float | None = None) -> None:
        self._inflight.pop(envelope.delivery_tag, None)
        new_envelope = JobQueueEnvelope(
            delivery_tag=envelope.delivery_tag,
            message=envelope.message,
            attempt=envelope.attempt + 1,
        )
        if delay:
            await asyncio.sleep(delay)
        self._queue.append(new_envelope)

    async def reject(self, envelope: JobQueueEnvelope) -> None:
        self._inflight.pop(envelope.delivery_tag, None)

    async def depth(self) -> int:
        return len(self._queue)


async def create_redis_backend(
    *,
    stream_name: str,
    group: str,
    consumer_name: str,
    redis_dsn: str,
) -> QueueBackendProtocol:
    """Create a Redis Streams backend.

    Замечание: функция использует ``redis.asyncio`` и предназначена для
    использования в реальной среде. В тестах она не вызывается, чтобы избежать
    необходимости поднимать Redis. Реализация упрощённая и поддерживает только
    чтение из одной группы/стрима.
    """

    import redis.asyncio as redis  # type: ignore[import]

    class RedisStreamBackend(InMemoryQueueBackend):
        def __init__(self, client: redis.Redis):
            super().__init__()
            self.name = "redis"
            self._client = client

        async def receive(self, *, timeout: float | None = None) -> JobQueueEnvelope | None:  # type: ignore[override]
            block_ms = int(timeout * 1000) if timeout else 1000
            entries = await self._client.xreadgroup(
                groupname=group,
                consumername=consumer_name,
                streams={stream_name: ">"},
                count=1,
                block=block_ms,
            )
            if not entries:
                return None
            _, records = entries[0]
            record_id, data = records[0]
            payload = json.loads(data[b"payload"].decode("utf-8"))
            message = JobQueueMessage.model_validate(payload)
            envelope = JobQueueEnvelope(delivery_tag=record_id, message=message, attempt=int(data.get(b"attempt", b"1")))
            self._inflight[record_id] = envelope
            return envelope

        async def ack(self, envelope: JobQueueEnvelope) -> None:  # type: ignore[override]
            self._inflight.pop(envelope.delivery_tag, None)
            await self._client.xack(stream_name, group, envelope.delivery_tag)
            await self._client.xdel(stream_name, envelope.delivery_tag)

        async def requeue(self, envelope: JobQueueEnvelope, *, delay: float | None = None) -> None:  # type: ignore[override]
            self._inflight.pop(envelope.delivery_tag, None)
            body = {
                "payload": json.dumps(envelope.message.model_dump()).encode("utf-8"),
                "attempt": str(envelope.attempt + 1).encode("utf-8"),
            }
            if delay:
                await asyncio.sleep(delay)
            await self._client.xadd(stream_name, body)
            await self._client.xack(stream_name, group, envelope.delivery_tag)

        async def reject(self, envelope: JobQueueEnvelope) -> None:  # type: ignore[override]
            self._inflight.pop(envelope.delivery_tag, None)
            await self._client.xack(stream_name, group, envelope.delivery_tag)

        async def depth(self) -> int:  # type: ignore[override]
            info = await self._client.xinfo_stream(stream_name)
            return info.get("length", 0)

    client = redis.from_url(redis_dsn, decode_responses=False)
    return RedisStreamBackend(client)


async def create_amqp_backend(
    *,
    amqp_url: str,
    queue_name: str,
) -> QueueBackendProtocol:
    """Create an AMQP (RabbitMQ) backend using :mod:`aio_pika`.

    Подключение устанавливается при первом вызове и повторно использует канал.
    Как и Redis-адаптер, эта функция не вызывается в тестах и служит
    ориентиром для прод-окружения.
    """

    import aio_pika

    class AMQPBackend(InMemoryQueueBackend):
        def __init__(self, connection: aio_pika.RobustConnection, queue: aio_pika.abc.AbstractRobustQueue):
            super().__init__()
            self.name = "amqp"
            self._connection = connection
            self._queue = queue

        async def receive(self, *, timeout: float | None = None) -> JobQueueEnvelope | None:  # type: ignore[override]
            message = await self._queue.get(timeout=timeout)
            if message is None:
                return None
            payload = json.loads(message.body.decode("utf-8"))
            job_message = JobQueueMessage.model_validate(payload)
            envelope = JobQueueEnvelope(
                delivery_tag=str(message.delivery_tag),
                message=job_message,
                attempt=int(message.headers.get("attempt", 1)),
            )
            self._inflight[envelope.delivery_tag] = envelope
            envelope.message.metadata.setdefault("_amqp_message", message)
            return envelope

        async def ack(self, envelope: JobQueueEnvelope) -> None:  # type: ignore[override]
            message = envelope.message.metadata.pop("_amqp_message")
            self._inflight.pop(envelope.delivery_tag, None)
            await message.ack()  # type: ignore[no-untyped-call]

        async def requeue(self, envelope: JobQueueEnvelope, *, delay: float | None = None) -> None:  # type: ignore[override]
            message = envelope.message.metadata.pop("_amqp_message")
            await message.reject(requeue=False)  # type: ignore[no-untyped-call]
            headers = dict(message.headers or {})
            headers["attempt"] = envelope.attempt + 1
            new_message = aio_pika.Message(
                body=json.dumps(envelope.message.model_dump()).encode("utf-8"),
                headers=headers,
            )
            if delay:
                await asyncio.sleep(delay)
            await self._queue.channel.default_exchange.publish(new_message, routing_key=queue_name)
            self._inflight.pop(envelope.delivery_tag, None)

        async def reject(self, envelope: JobQueueEnvelope) -> None:  # type: ignore[override]
            message = envelope.message.metadata.pop("_amqp_message")
            self._inflight.pop(envelope.delivery_tag, None)
            await message.reject(requeue=False)  # type: ignore[no-untyped-call]

        async def depth(self) -> int:  # type: ignore[override]
            return self._queue.declaration_result.message_count  # type: ignore[no-any-return]

    connection: aio_pika.RobustConnection = await aio_pika.connect_robust(amqp_url)
    channel = await connection.channel()
    queue = await channel.declare_queue(queue_name, durable=True)
    return AMQPBackend(connection, queue)


async def default_native_executor(
    job: Job,
    profile_toggles: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> JobResult:
    """Execute ``job`` using the synchronous native runner in a worker thread."""

    return await anyio.to_thread.run_sync(run_native_job, job)


async def default_orchestrator_executor(
    job: Job,
    profile_toggles: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> JobResult:
    """Execute ``job`` through the orchestrator Gateway client."""

    gateway_url = metadata.get("gateway_url") or os.environ.get("GATEWAY_URL")
    gateway_token = metadata.get("gateway_token") or os.environ.get("GATEWAY_TOKEN")
    if not gateway_url or not gateway_token:
        raise RuntimeError("Gateway URL and token are required for orchestrator mode")
    poll_timeout = float(metadata.get("poll_timeout", os.environ.get("WORKER_POLL_TIMEOUT", 90.0)))
    poll_interval = float(metadata.get("poll_interval", os.environ.get("WORKER_POLL_INTERVAL", 1.0)))
    async with create_gateway_client(str(gateway_url), str(gateway_token)) as client:
        return await run_orchestrated_job(
            job,
            client,
            poll_timeout=float(poll_timeout),
            poll_interval=float(poll_interval),
        )

