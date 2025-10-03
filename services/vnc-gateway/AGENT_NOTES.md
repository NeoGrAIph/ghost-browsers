# AGENT_NOTES — vnc-gateway

## Overview
FastAPI service that validates short-lived VNC access tokens and proxies HTTP/WS traffic from the public Gateway to the Runner instances.

## Interfaces
- `GET /sessions/{session_id}` — prefers `X-VNC-Token` header; falls back to `token`/`access_token` query parameters for pre-signed URLs; proxies to Runner HTTP API.
- `WS /sessions/{session_id}/ws` — validates `X-VNC-Token` header and the same `token`/`access_token` query fallback before establishing the bidirectional tunnel to the Runner websocket endpoint.
- `GET /metrics` — Prometheus exposition endpoint (text format) when the Prometheus backend is enabled; returns `404` when OTLP-only metrics are configured.

## Data & Models
- `Settings` (`app/camou_vnc_gateway/config.py`): environment-driven configuration using `pydantic-settings`. Includes runner HTTP/WS base URLs and shared token secret.
- `TokenValidator`: валидирует HS256 JWT с claim'ами `sid`, `exp`, `iss`, `sub`; хранит in-memory кэш `(nonce, iat)` для защиты от повторного использования токенов (per-session `OrderedDict` с лимитом и учётом TTL).
- `metrics` (`app/camou_vnc_gateway/metrics.py`): конфигурируемый набор бэкендов. По умолчанию поднимает отдельный `CollectorRegistry` (gauge/counter для соединений и ошибок токенов). Через настройки можно подключить внешний `CollectorRegistry` или OTLP-экспортёр (`MetricsEventExporter`). `/metrics` отдает payload только для Prometheus-конфигурации.

- Токены — стандартные HS256 JWT; валидация выполняется через `python-jose` с проверкой `iss`, `exp`, `sid` и `iat`, после чего nonce/`iat` попадает в кэш чтобы предотвращать replay.
- Connection metrics backed by in-memory `ConnectionRegistry` with async context manager; логируем события и одновременно обновляем Prometheus-gauge/counter в собственном registry.
- WebSocket proxy теперь использует `uvicorn`-совместимый backend (`websockets.connect` + `asyncio.TaskGroup`) вместо ручного релея: two tasks pump with idle/send timeouts и повторно используют production defaults (`open_timeout`, `max_queue`, `ping_interval=None`).
- Dependency wiring relies on `typing.Annotated` wrappers to avoid Ruff `B008` violations while keeping FastAPI semantics.
- Tests inject stubbed `RunnerProxy` via dependency overrides; `tests/conftest.py` adjusts `sys.path` instead of installing the package.
- Runner proxy keeps a singleton `httpx.AsyncClient` and resolves `target_port` from query/referer/cookie (persisting it via `vnc-target-port` cookie) to build Runner URLs with configurable prefixes; WebSocket relay теперь ждёт оба направления через `TaskGroup`, отдаёт 1008 при невалидном `target_port` и 1011 при timeouts/сетевых ошибках.
- Prometheus экспозиция реализована через `/metrics`, чтобы scrape-еры (Prometheus, VictoriaMetrics и т.д.) могли использовать стандартный текстовый формат без дополнительных middleware.

## Decisions
- 2025-02-14 · Runtime-образ собирается через builder-стейдж, который упаковывает сервис в wheel. Финальный слой устанавливает wheel и копирует исходники `app/`, поэтому рантайм остаётся лёгким, но при необходимости сохраняется возможность отладки по исходникам. Перед сборкой образа make-таргет `vnc-gateway-image` выполняет smoke-проверки (`ruff`, `pytest`), чтобы pipeline не публиковал образ с регрессиями.
- Helm chart `docs/helm/platform` предоставляет шаблон Deployment/Service/Ingress для VNC Gateway, принимает `secretEnv` c общим `VNC_GATEWAY_TOKEN_SECRET` и прочими секретами, обеспечивая синхронизацию конфигурации с Gateway/Runner.
- Dockerfile ожидает корректный PEP 517 backend (`poetry-core`): без `[build-system]` wheel собирался с метаданными версии `0.0.0` и без зависимостей, что ломало установку `uvicorn` в рантайме. `pyproject` фиксирован и дополнен `authors` для совместимости с Poetry package mode.
- 2025-10-25 · gpt-5-codex · HTTP и WebSocket маршруты принимают токен как из заголовка, так и из `token`/`access_token` query-параметров, что упрощает использование iframe/предподписанных ссылок; добавлены unit-тесты fallback.

## Constraints & Invariants
- Tokens must include the matching session identifier; mismatches immediately rejected.
- `iat` допускает максимум `clock_skew_tolerance_seconds` (10 секунд) относительно сервера; reuse токена до истечения TTL запрещён.
- Only `ws`/`wss` schemes accepted for Runner WS base; HTTP base limited to `http/https`.
- `ConnectionRegistry` is process-local and not durable; acceptable for current scope. Gauge удаляется после закрытия последнего соединения, чтобы не накапливать пустые time-series.
- Локальный `docker-compose` использует `VNC_GATEWAY_TOKEN_SECRET=dev-secret`, если переменная не передана. Для production/
  shared стендов секрет обязан быть переопределён и согласован с Gateway.
- Сервис остаётся частью публичного периметра: проверка VNC-токена обязательна даже для запросов,
  поступающих из кластера. Беспарольный режим распространяется только на REST/SSE/WS Gateway.
- `/metrics` рассчитан на scrape раз в ≤30s; registry in-memory, поэтому при перезапуске значения счётчиков обнуляются. При работе с OTLP-бэкендом HTTP-экспорт отключается (отдаём `404`).
- Query fallback никогда не отключает проверку заголовка: если одновременно передано несколько значений, выигрывает заголовок `X-VNC-Token`; query-параметры используются только как запасной канал.

## Known Gaps / TODO
- [x] Replace manual websocket proxy with production-ready solution once Runner API stabilises (e.g. uvicorn websockets integration). (Done in this iteration.)
- [x] Integrate metrics registry with Prometheus/OpenTelemetry backend when available. (Customisable backend wired via settings.)
- [x] Harden token validator against replay (нужен учёт `iat`/одноразовых токенов поверх проверки истечения). (Implemented in-memory nonce/`iat` cache.)

## How to Test
```bash
cd services/vnc-gateway
poetry install --with dev --no-root
poetry run ruff check .
poetry run pytest -q
```

## Changelog (for agents)
Дата · Кем/чем изменено · Коротко *что и почему*.

- 2025-10-10 · gpt-5-codex · Добавлена конфигурация метрик через настройки (Prometheus registry/OTLP exporter), обновлён `/metrics` endpoint и покрытие тестами.
- 2025-10-09 · gpt-5-codex · Переписан WS-прокси на uvicorn/websockets `TaskGroup`-relay, добавлены интеграционные тесты с real сервером, внедрён Prometheus `/metrics` (active/total connections, token failures), расширен `TokenValidator` (nonce/iat cache) и документирован сценарий предотвращения replay.
- 2025-10-03 · gpt-5-codex · Добавлен дефолт `VNC_GATEWAY_TOKEN_SECRET=dev-secret` для локального docker-compose и описан опциональный override.
- 2025-10-03 · gpt-5-codex · Дополнен `pyproject.toml` блоком `[build-system]` (`poetry-core`) и полем `authors`, чтобы docker build устанавливал wheel вместе с зависимостями (`uvicorn` и др.).
- 2025-10-03 · gpt-5-codex · Добавлены Helm-шаблоны/values для VNC Gateway с примерами секретов и документация по установке.
- 2025-02-14 · gpt-5-codex · Добавлен Dockerfile с многоступенчатой сборкой, make/CI-таргеты для образа и документация по переменным окружения VNC Gateway.
- 2025-10-25 · gpt-5-codex · Добавлен fallback обработки токена через query `token`/`access_token`, обновлены роуты и unit-тесты ключевых сценариев.
