# Camoufox Worker

## Job Contract

### Request (`worker.jobs.Job`)
- `url` (`HttpUrl`, required) — адрес страницы для открытия.
- `http_proxy` / `https_proxy` / `socks_proxy` (`str | None`) — необязательные строки подключения к прокси.
- `timeout_sec` (`int`, default `60`) — общий таймаут задачи.

### Result (`worker.jobs.JobResult`)
- `status` (`success | failure | aborted`) — итог выполнения.
- `ok` (`bool`) — true, если `status == success`.
- `started_at` / `finished_at` (`datetime`, UTC) — временные метки запуска и завершения.
- `metrics.duration_ms` (`float`) — продолжительность выполнения; дополнительные метрики складываются в `metrics.extra`.
- `title` (`str | None`) — пример артефакта из нативного раннера (заголовок страницы).
- `error` (`JobError | None`) — тип/сообщение ошибки, если выполнение завершилось неуспешно.

## CLI Output
```bash
python -m worker.main run --mode=native --url=https://example.com
```
возвращает JSON, сериализованный из `JobResult` (без `null` полей).

## Container Runtime

Собранный образ запускается через `bin/worker-launch.sh`, который прокидывает
переменные окружения в CLI `worker.main`. Без аргументов скрипт ожидает
переменную `WORKER_JOB_URL`; остальные настройки опциональны:

| Переменная | Назначение | Значение по умолчанию |
| --- | --- | --- |
| `WORKER_JOB_URL` | URL для навигации Camoufox | — (обязателен) |
| `WORKER_MODE` | `native` или `orchestrator` | `native` |
| `WORKER_TIMEOUT` | Таймаут выполнения (сек) | `60` |
| `WORKER_POLL_TIMEOUT` | Таймаут ожидания готовности сессии (сек) | `90` |
| `WORKER_POLL_INTERVAL` | Интервал опроса orchestrator-сессии (сек) | `1` |
| `WORKER_GATEWAY_URL` | Алиас `GATEWAY_URL` для orchestrator | — |
| `WORKER_GATEWAY_TOKEN` | Алиас `GATEWAY_TOKEN` для orchestrator | — |
| `WORKER_EXTRA_ARGS` | Дополнительные флаги CLI (строка) | — |
| `WORKER_PROFILE_TOGGLES` | Тумблеры профиля Camoufox (`key=value,key2=value2`) | — |

Примеры запуска:

```bash
# Проверка CLI (перенаправление аргументов)
docker run --rm ghcr.io/<org>/camoufox-worker:latest -- --help

# Нативный режим
docker run --rm \
  -e WORKER_JOB_URL=https://example.com \
  -e WORKER_TIMEOUT=30 \
  ghcr.io/<org>/camoufox-worker:latest

# Orchestrator-режим
docker run --rm \
  -e WORKER_JOB_URL=https://example.com \
  -e WORKER_MODE=orchestrator \
  -e WORKER_GATEWAY_URL=https://gateway.local \
  -e WORKER_GATEWAY_TOKEN=secret-token \
  ghcr.io/<org>/camoufox-worker:latest
```

## Queue Consumer & Metrics

Модуль `worker.queue` реализует асинхронный консьюмер задач, совместимый с
Redis Streams, AMQP (RabbitMQ) и встроенным in-memory backend для тестов. Он
получает сообщения, описанные моделью `JobQueueMessage`, и делегирует их
исполнителям нативного и orchestrator-режима. Дополнительно включены:

- **Ретраи и идемпотентность.** Сообщение содержит `max_attempts` и
  `idempotency_key`; при успехе повторные доставки с тем же ключом
  игнорируются.
- **Prometheus-метрики.** Экспортируются счётчики/гистограммы
  (`camoufox_worker_job_*`, `camoufox_worker_queue_depth`).
- **Структурированные логи.** События (`job_received`, `job_retry` и др.)
  сериализуются в JSON.

### Пример конфигурации Redis Streams

```python
import asyncio
from worker.queue import (
    JobQueueConsumer,
    JobQueueMessage,
    create_redis_backend,
    default_native_executor,
    default_orchestrator_executor,
    load_default_profile_toggles,
)


async def main() -> None:
    backend = await create_redis_backend(
        redis_dsn="redis://localhost:6379/0",
        stream_name="camoufox-jobs",
        group="workers",
        consumer_name="worker-1",
    )
    consumer = JobQueueConsumer(
        backend,
        native_executor=default_native_executor,
        orchestrator_executor=default_orchestrator_executor,
        default_profile_toggles=load_default_profile_toggles(),
    )
    await consumer.run()


asyncio.run(main())
```

### Профильные тумблеры

Тумблеры можно задавать глобально через `WORKER_PROFILE_TOGGLES` (например,
`headless=virtual,trace=0`) и/или в сообщении очереди (`profile_toggles`). При
выполнении задачи они прокидываются в окружение под именами
`CAMOUFOX_TUMBLER_<KEY>`, что позволяет тонко настраивать поведение браузера
без изменения кода.
