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
