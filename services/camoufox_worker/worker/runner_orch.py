"""Async HTTP helpers for orchestrating sessions via the public gateway."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import httpx

from .jobs import Job, JobError, JobMetrics, JobResult, JobStatus

DEFAULT_TIMEOUT = 10.0
RETRY_STATUS_CODES = (500, 502, 503, 504)


class GatewayRequestError(RuntimeError):
    """Raised when the gateway rejects a request after exhausting retries."""


def create_gateway_client(
    base_url: str,
    token: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Return an authenticated :class:`httpx.AsyncClient` for the gateway.

    Parameters
    ----------
    base_url:
        Базовый URL публичного Gateway (например, ``https://gateway.example``).
    token:
        Bearer-токен для аутентификации HTTP-запросов.
    timeout:
        Таймаут в секундах, применяемый к каждому запросу (по умолчанию 10 сек).
    transport:
        Необязательный транспорт (например, ``httpx.MockTransport``) — удобно
        использовать в unit-тестах.

    Returns
    -------
    httpx.AsyncClient
        Клиент с установленным заголовком ``Authorization`` и JSON Accept.

    Examples
    --------
    >>> client = create_gateway_client("https://gateway", "token")
    >>> isinstance(client, httpx.AsyncClient)
    True
    """

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        headers=headers,
        transport=transport,
    )


async def create_session(
    client: httpx.AsyncClient,
    payload: Mapping[str, Any],
    *,
    retries: int = 3,
    backoff: float = 0.5,
) -> Dict[str, Any]:
    """Create a session via ``POST /sessions/commands`` and return the payload.

    Parameters
    ----------
    client:
        Предварительно аутентифицированный ``httpx.AsyncClient``.
    payload:
        Тело запроса, совместимое с контрактом ``POST /sessions/commands``.
    retries:
        Количество повторов при сетевых и 5xx ошибках (по умолчанию 3).
    backoff:
        Базовая задержка (сек) перед повтором; увеличивается экспоненциально.

    Returns
    -------
    dict[str, Any]
        JSON-ответ Gateway, преобразованный в словарь.

    Raises
    ------
    GatewayRequestError
        Если запрос завершился ошибкой после всех ретраев.
    """

    response = await _request_with_retry(
        client,
        "POST",
        "/sessions/commands",
        json=dict(payload),
        expected_status=(201,),
        retries=retries,
        backoff=backoff,
    )
    return response.json()


async def update_session_proxy(
    client: httpx.AsyncClient,
    session_id: str,
    proxy_payload: Mapping[str, Any],
    *,
    retries: int = 3,
    backoff: float = 0.5,
) -> Dict[str, Any]:
    """Update proxy configuration via ``POST /sessions/{id}/proxy``.

    Parameters
    ----------
    client:
        Аутентифицированный HTTP-клиент Gateway.
    session_id:
        Идентификатор сессии, возвращённый ``create_session``.
    proxy_payload:
        Поля, соответствующие ``SessionProxySettings`` (минимум одно значение).
    retries:
        Допустимое число повторов при временных сбоях.
    backoff:
        Базовый интервал экспоненциальной задержки перед ретраем.

    Returns
    -------
    dict[str, Any]
        Обновлённое состояние сессии.

    Raises
    ------
    GatewayRequestError
        При исчерпании ретраев или неожидаемом HTTP-статусе.
    """

    response = await _request_with_retry(
        client,
        "POST",
        f"/sessions/{session_id}/proxy",
        json=dict(proxy_payload),
        expected_status=(200,),
        retries=retries,
        backoff=backoff,
    )
    return response.json()


async def touch_session(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    timestamp: datetime | None = None,
    retries: int = 3,
    backoff: float = 0.5,
) -> Dict[str, Any]:
    """Send ``POST /sessions/{id}/touch`` to refresh ``last_seen_at``.

    Parameters
    ----------
    client:
        Аутентифицированный HTTP-клиент Gateway.
    session_id:
        Целевая сессия.
    timestamp:
        Пользовательский таймстемп (UTC); по умолчанию используется текущее время.
    retries:
        Количество ретраев при временных ошибках.
    backoff:
        Базовый интервал экспоненциальной задержки.

    Returns
    -------
    dict[str, Any]
        Обновлённое состояние сессии.

    Raises
    ------
    GatewayRequestError
        Если запрос неоднократно завершился ошибкой.
    """

    timestamp = timestamp or datetime.now(tz=UTC)
    payload = {"timestamp": timestamp.isoformat()}
    response = await _request_with_retry(
        client,
        "POST",
        f"/sessions/{session_id}/touch",
        json=payload,
        expected_status=(200,),
        retries=retries,
        backoff=backoff,
    )
    return response.json()


async def delete_session(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    retries: int = 3,
    backoff: float = 0.5,
) -> None:
    """Issue ``DELETE /sessions/{id}`` and swallow 404 responses gracefully.

    Parameters
    ----------
    client:
        Аутентифицированный HTTP-клиент Gateway.
    session_id:
        Идентификатор сессии.
    retries:
        Максимальное количество повторов для временных ошибок.
    backoff:
        Базовый интервал экспоненциальной задержки.

    Raises
    ------
    GatewayRequestError
        При ошибках сети или неожидаемом статусе, отличном от ``204``/``404``.
    """

    await _request_with_retry(
        client,
        "DELETE",
        f"/sessions/{session_id}",
        expected_status=(204, 404),
        retries=retries,
        backoff=backoff,
    )


async def poll_session_status(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    target_statuses: Sequence[str] = ("READY",),
    poll_interval: float = 1.0,
    poll_timeout: float = 60.0,
    retries: int = 3,
    backoff: float = 0.5,
) -> Tuple[Dict[str, Any], int]:
    """Poll ``GET /sessions/{id}`` until it reaches one of ``target_statuses``.

    Parameters
    ----------
    client:
        Аутентифицированный HTTP-клиент Gateway.
    session_id:
        Целевая сессия.
    target_statuses:
        Набор статусов (в верхнем регистре), при достижении которых polling
        завершается успехом.
    poll_interval:
        Интервал (сек) между успешными запросами.
    poll_timeout:
        Общее время ожидания (сек) до генерации ``asyncio.TimeoutError``.
    retries:
        Количество повторов при временных сетевых/серверных сбоях.
    backoff:
        Базовая задержка перед ретраем запросов, завершившихся ошибкой.

    Returns
    -------
    tuple[dict[str, Any], int]
        Кортеж из последнего ответа Gateway и количества выполненных попыток.

    Raises
    ------
    asyncio.TimeoutError
        Если целевой статус не достигнут за ``poll_timeout`` секунд.
    GatewayRequestError
        При исчерпании ретраев.
    """

    start = time.perf_counter()
    attempts = 0
    while True:
        attempts += 1
        response = await _request_with_retry(
            client,
            "GET",
            f"/sessions/{session_id}",
            expected_status=(200,),
            retries=retries,
            backoff=backoff,
        )
        payload = response.json()
        status = str(payload.get("status", "")).upper()
        if status in {value.upper() for value in target_statuses}:
            return payload, attempts

        elapsed = time.perf_counter() - start
        if elapsed >= poll_timeout:
            raise asyncio.TimeoutError(
                f"Timed out after {poll_timeout}s waiting for status in {target_statuses}"
            )
        await asyncio.sleep(poll_interval)


async def run_orchestrated_job(
    job: Job,
    client: httpx.AsyncClient,
    *,
    poll_interval: float = 1.0,
    poll_timeout: float = 60.0,
    idle_ttl_seconds: int | None = None,
    retries: int = 3,
    backoff: float = 0.5,
) -> JobResult:
    """Execute a job via the orchestrator flow and return a :class:`JobResult`.

    Parameters
    ----------
    job:
        Pydantic-модель с параметрами задачи.
    client:
        Аутентифицированный HTTP-клиент Gateway (см. ``create_gateway_client``).
    poll_interval:
        Интервал между запросами ``GET /sessions/{id}``.
    poll_timeout:
        Максимальное время ожидания целевого статуса.
    idle_ttl_seconds:
        Необязательное переопределение ``idle_ttl_seconds`` для создаваемой
        сессии. Если не указано — используется ``job.timeout_sec`` (с ограниче-
        нием 30–3600 секунд).
    retries:
        Количество повторов при сетевых и серверных ошибках.
    backoff:
        Базовая задержка (сек) перед ретраями, применяется экспоненциально.

    Returns
    -------
    JobResult
        Структурированный результат выполнения оркестраторного сценария.

    Notes
    -----
    Функция создаёт сессию, при необходимости настраивает прокси, ожидает
    статуса ``READY``, отправляет ``touch`` и гарантированно пытается удалить
    сессию в финале.
    """

    started_at = datetime.now(tz=UTC)
    started_perf = time.perf_counter()
    status = JobStatus.SUCCESS
    error: Optional[JobError] = None
    session_id: Optional[str] = None
    metrics_extra: Dict[str, Any] = {
        "mode": "orchestrator",
    }

    try:
        payload = _job_to_session_payload(job, idle_ttl_seconds)
        session = await create_session(
            client,
            payload,
            retries=retries,
            backoff=backoff,
        )
        session_id = str(session.get("id")) if session.get("id") is not None else None
        if session_id:
            metrics_extra["session_id"] = session_id

        proxy_payload = _job_to_proxy_payload(job)
        if session_id and proxy_payload:
            session = await update_session_proxy(
                client,
                session_id,
                proxy_payload,
                retries=retries,
                backoff=backoff,
            )

        if session_id:
            poll_result, attempts = await poll_session_status(
                client,
                session_id,
                poll_interval=poll_interval,
                poll_timeout=poll_timeout,
                retries=retries,
                backoff=backoff,
            )
            metrics_extra["poll_attempts"] = attempts
            metrics_extra["session_status"] = poll_result.get("status")
            metrics_extra["last_seen_at"] = poll_result.get("last_seen_at")

            touched = await touch_session(
                client,
                session_id,
                retries=retries,
                backoff=backoff,
            )
            if "last_seen_at" in touched:
                metrics_extra["touched_at"] = touched["last_seen_at"]
    except asyncio.TimeoutError as exc:
        status = JobStatus.FAILURE
        error = JobError(type=exc.__class__.__name__, message=str(exc))
    except GatewayRequestError as exc:
        status = JobStatus.FAILURE
        error = JobError(type=exc.__class__.__name__, message=str(exc))
    finally:
        if session_id:
            try:
                await delete_session(
                    client,
                    session_id,
                    retries=retries,
                    backoff=backoff,
                )
            except GatewayRequestError as exc:
                metrics_extra["cleanup_error"] = str(exc)
                status = JobStatus.FAILURE
                if error is None:
                    error = JobError(type=exc.__class__.__name__, message=str(exc))

    finished_at = datetime.now(tz=UTC)
    metrics = JobMetrics(
        duration_ms=(time.perf_counter() - started_perf) * 1000.0,
        extra=metrics_extra,
    )
    return JobResult(
        job=job,
        status=status,
        ok=status is JobStatus.SUCCESS,
        started_at=started_at,
        finished_at=finished_at,
        metrics=metrics,
        error=error,
    )


def _job_to_session_payload(job: Job, idle_ttl_seconds: int | None = None) -> Dict[str, Any]:
    """Convert a :class:`Job` into a payload for ``POST /sessions/commands``."""

    ttl = idle_ttl_seconds if idle_ttl_seconds is not None else int(job.timeout_sec)
    ttl = max(30, min(int(ttl), 3600))
    payload: Dict[str, Any] = {
        "browser": "camoufox",
        "headless": True,
        "idle_ttl_seconds": ttl,
        "start_url": job.url_source,
        "labels": {
            "worker_mode": "orchestrator",
        },
        "metadata": {
            "job_timeout_sec": job.timeout_sec,
        },
    }
    proxy_payload = _job_to_proxy_payload(job)
    if proxy_payload:
        payload["proxy"] = proxy_payload
    return payload


def _job_to_proxy_payload(job: Job) -> Dict[str, str] | None:
    """Return a ``SessionProxySettings``-compatible mapping for the job."""

    proxy_payload = {
        "http": job.http_proxy,
        "https": job.https_proxy,
        "socks": job.socks_proxy,
    }
    compact = {key: value for key, value in proxy_payload.items() if value}
    return compact or None


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: Mapping[str, Any] | None = None,
    expected_status: Sequence[int] = (200,),
    retries: int = 3,
    backoff: float = 0.5,
) -> httpx.Response:
    """Execute an HTTP request with retry semantics for transient failures."""

    attempt = 0
    last_error: Optional[BaseException] = None
    while attempt <= retries:
        try:
            response = await client.request(method, path, json=json)
            if response.status_code not in expected_status:
                if response.status_code >= 400:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise exc
                raise GatewayRequestError(
                    f"Unexpected status {response.status_code} for {method} {path}"
                )
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code
            if status_code in RETRY_STATUS_CODES and attempt < retries:
                await asyncio.sleep(backoff * (2**attempt))
                attempt += 1
                continue
            raise GatewayRequestError(
                f"Gateway rejected {method} {path} with status {status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(backoff * (2**attempt))
                attempt += 1
                continue
            raise GatewayRequestError(
                f"Failed to execute {method} {path}: {exc}"
            ) from exc

    assert last_error is not None  # pragma: no cover - defensive guard
    raise GatewayRequestError(str(last_error))


__all__ = [
    "GatewayRequestError",
    "create_gateway_client",
    "create_session",
    "delete_session",
    "poll_session_status",
    "run_orchestrated_job",
    "touch_session",
    "update_session_proxy",
]
