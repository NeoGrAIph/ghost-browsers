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
