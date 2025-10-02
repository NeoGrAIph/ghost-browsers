# AGENT_NOTES — runner

## Overview
FastAPI-based service that manages browser sessions for Ghost Browsers. Provides in-memory lifecycle management, publishes session events, and exposes minimal HTTP endpoints for orchestration and health checks.

Warm workstation preloading is handled by ``app.warm_pool.WarmPoolManager`` which provisions Camoufox instances ahead of time, keeps fingerprint affinity, and exposes explicit slot state transitions.

## Interfaces
- **HTTP**
  - `GET /health` — возвращает `{status, runner_id, camoufox_path, slots, vnc, proxy, prewarm, ttl}`;
    `slots.total` считывается из `RunnerSettings.slot_limit`, `slots.active` — количество
    не-`DEAD` сессий; `prewarm` включает счётчик и последнюю ошибку прогрева;
    `ttl` содержит ближайшее истечение (`next_expiry_at`) и счетчики работы
    фонового reaper-а (`total_runs`, `expired_sessions`, `last_run_at`).
  - `POST /sessions` — accepts `SessionCreatePayload`, возвращает созданный `core.Session`.
    При отсутствии свободных warm-слотов возвращает HTTP 429 (`no warm workstations available`).
  - `PATCH /sessions/{id}` — accepts `SessionUpdatePayload`, merges labels/metadata, returns updated `core.Session`.
  - `POST /sessions/{id}/touch` — обновляет `last_seen_at`, продлевая TTL и публикуя heartbeat-событие.
  - `DELETE /sessions/{id}` — marks session as `DEAD`, returns terminal snapshot.
  - `GET /metrics` — Prometheus endpoint (``text/plain; version=0.0.4``) с gauge/counter-метриками
    runner-а: `runner_active_sessions`, `runner_reaper_runs_total`,
    `runner_reaper_expired_sessions_total`, `runner_reaper_last_run_timestamp`,
    `runner_vnc_allocations`, `runner_vnc_allocation_requests_total`.
  - `GET /workstations` — возвращает снимки состояния warm-пула (idle/reserved/busy).
  - `POST /workstations/reserve` — резервирует слот (по ID или первый idle) и отдаёт launch env.
  - `POST /workstations/{id}/busy` — переводит слот из reserved в busy.
  - `POST /workstations/{id}/cancel` — откатывает неудачное резервирование в idle.
  - `POST /workstations/{id}/release` — рециклирует busy слот обратно в idle.
- **Event transport**
  - `SessionEventPublisher.publish(SessionEvent)` — protocol for pushing lifecycle events downstream. Default implementation stores events in memory (`InMemorySessionEventPublisher`) but can be swapped for HTTP/SSE bridges via `CallbackSessionEventPublisher`.
  - `HttpSessionEventPublisher` — при наличии `RunnerSettings.event_endpoint` POST-ит события на `gateway /events`.

## Data & Models
- Uses `core.Session`, `SessionEvent`, `SessionProxySettings`, `SessionVncDetails`, and related enums.
- Local payload models (`SessionCreatePayload`, `SessionUpdatePayload`) act as request DTOs before conversion into immutable core models.
- Sessions are keyed by UUID and persisted in-memory; timestamps sourced from an injectable clock (UTC aware).
- `SessionManagerMetrics` агрегирует счётчик активных сессий и историю ошибок прогрева (bounded deque по
  `RunnerSettings.prewarm_failure_history_size`), ближайшее истечение TTL и статистику
  фонового reaper-а (кол-во запусков, количество завершённых сессий и отметку последнего запуска).
- Prometheus-инструментация живёт в `app.metrics` и использует отдельный `CollectorRegistry`;
  `SessionManager` синхронизирует gauge/counter-метрики при создании/завершении сессий,
  аллокации VNC и работе idle-reaper-а.
- Конфигурация пула прогретых рабочих станций описывается `WarmPoolConfig`
  (`app.config.warm_pool`). Запись (`WorkstationConfigEntry`) содержит хотя бы `id`
  (строгая уникальность, проверяется валидатором) и произвольные дополнительные поля
  (разрешены `extra`, чтобы операторы могли добавлять свои атрибуты). JSON-файл читается
  при старте через `load_warm_pool_config`, I/O и ошибки сериализации/валидации оборачиваются
  в `WarmPoolConfigError`.

## Decisions
- **In-memory publisher**: Стандартный транспорт построен на `InMemorySessionEventPublisher` и считается продукционным решением; при необходимости можно оборачивать его через `CallbackSessionEventPublisher` для сторонних интеграций без отказа от in-memory ядра.
- **HTTP publisher toggle**: `get_event_publisher` читает `RunnerSettings.event_endpoint` и, если URL задан, использует `HttpSessionEventPublisher`, публикующий события в Gateway через `POST /events`.
- **Workstation events**: маршруты `/workstations` используют `WorkstationEventPublisher` (по умолчанию `InMemoryWorkstationEventPublisher`) и транслируют `WorkstationEvent` для синхронизации warm-пула с Gateway/UI.
- **Camoufox stub dependency**: Для unit-тестов в CI runner использует локальный путь-зависимость `packages/camoufox`, реализующую CLI/API-совместимый stub. Это позволяет выполнять `poetry install` без доступа к проприетарному пакету.
- **Process-backed VNC controller**: Non-headless sessions allocate Xvfb/x11vnc/websockify helpers via `ProcessVncController`. The controller maintains a bounded pool of displays and ports, composes public HTTP/WS URLs from `RunnerSettings`, and tears down helpers whenever sessions terminate or switch to headless mode.
- **Gateway-signed VNC tokens**: Runner never persists VNC `token` or `token_ttl_seconds`; any user-supplied values are stripped and synthetic descriptors leave them `None` so that the gateway can issue signed credentials.
- **Environment-driven settings**: `RunnerSettings.from_env` centralises configuration parsing without extra dependencies, easing future extension. Дополнительные параметры: `slot_limit`, базовые VNC URL, глобальный флаг прокси и ёмкость истории ошибок прогрева.
- **Bounded prewarm history**: менеджер хранит ошибки прогрева в `deque` с ограничением размера, что позволяет health-эндпоинту
  показывать последние сбои без риска утечки памяти.
- **Warm pool-backed sessions**: `SessionManager` теперь зависит от `WarmPoolManager`, резервирует слот до создания сессии и
  рециклирует его при завершении. В случае исчерпания слотов API возвращает 429.
- **Gateway proxy compatibility**: `SessionCreatePayload` остаётся публичным контрактом, но теперь вызывается через Gateway, потому важна обратная совместимость и строгая валидация.
- **Playwright launch lifecycle**: `app.browser.launch_browser` стартует Playwright в режиме `launch-server`, сохраняет `wsEndpoint`/PID в метаданных и позволяет `SessionManager` останавливать процесс при переходе в `DEAD` или очистке endpoint. Исключения при старте выполняют откат без публикации событий.
- **Idle TTL reaper**: `SessionManager` содержит AnyIO-based reaper, который вызывает
  `reap_expired_sessions`, завершает истёкшие по `idle_ttl_seconds` сессии и публикует события
  `session.ended` с reason=`idle-timeout`. Запускается/останавливается через `start()`/`stop()` и
  lifecycle-хуки FastAPI.
- **Prometheus registry**: Runner экспортирует `/metrics`, используя
  `prometheus_client.CollectorRegistry`; значения обновляются в момент изменения состояния
  (`active_sessions`, VNC аллокации, пробеги reaper-а) вместо ленивой агрегации на запрос.
- **JSON-конфиг пула прогрева**: Дополнительные параметры окружения (`WARM_POOL_CONFIG_PATH`,
  `BROWSER_PREFS_PATH`, `PREWARM_NAVIGATION`, `START_URL`, `START_URL_WAIT_MS`) разбираются в
  `RunnerSettings`. Отдельный JSON-файл описывает warm pool; при ошибках чтения/валидации
  старт завершается с развёрнутым сообщением, что упрощает операционную диагностику.
- **Warm pool state machine**: ``WarmPoolManager`` использует явные состояния (`idle → reserved → busy → recycling`, а также `draining`/`error`) и индивидуальные ``asyncio.Lock`` для каждой рабочей станции. Это предотвращает гонки при параллельных резервациях и гарантирует, что recycle всегда закрывает процесс, чистит профили и перезапускает Camoufox с тем же fingerprint.

## Constraints & Invariants
- `RunnerSettings.vnc_token_ttl_seconds` capped at 300 seconds to align with `SessionVncDetails` validation.
- `SessionManager` always updates `last_seen_at` on mutations to ensure monotonic timestamps.
- `SessionEvent` timestamps are UTC and emitted for every state change; terminal events require `SessionStatus.DEAD`.
- Session mutations occur under an `anyio.Lock` to avoid race conditions in async contexts.
- Health payload normalises proxy base URLs by stripping trailing slashes
  only when the configured path is empty, preserving operator-provided
  values.
- Idle reaper использует инъецируемые часы и общее состояние `SessionManager`; пересчёт ближайшего TTL выполняется после любых
  апдейтов/завершений, чтобы метрики `next_expiry_at`/`reaper` оставались консистентными.
- Взаимодействие с Gateway/SSE происходит только внутри доверенной сети кластера; авторизация на уровне HTTP не ожидается,
  вместо этого требуется сетевое разделение и настройка доверенных CIDR на стороне Gateway.
- Доступность VNC зависит от бинарей `Xvfb`, `x11vnc` и `websockify`; при их отсутствии `ProcessVncController` отключается и сессии остаются без VNC-URL.

## Known Gaps / TODO
- [ ] Зафиксировать профиль нагрузки для in-memory издателя после появления боевых метрик, чтобы подтвердить соответствие latency требованиям.

## How to Test
- `poetry install --no-root`
- `PYTHONPATH=. poetry run pytest -q` (anyio-powered unit tests)
- `poetry run ruff check .`
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_config_warm_pool.py -q`
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_warm_pool.py -q`
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_workstations_api.py -q`

## Changelog (for agents)
- 2024-09-22 · OpenAI ChatGPT · Расширен `/health`, добавлены метрики/история prewarm, новые настройки и модульные тесты.
- 2025-10-05 · gpt-5-codex · Sanitised runner VNC payloads to defer token issuance to the gateway and extended unit tests.
- 2025-10-07 · gpt-5-codex · Зафиксировано использование in-memory event publisher как основного транспорта, обновлены Known Gaps.
- 2025-10-08 · gpt-5-codex · Добавлен HTTP publisher (`POST /events`) и покрытие unit-тестами + конфиг-переключатель в зависимостях.
- 2025-10-09 · gpt-5-codex · Переключили зависимость `camoufox` на локальный stub-пакет и нормализовали выдачу proxy URL в `/health`,
  чтобы `poetry install` и unit-тесты проходили в офлайн-окружении без лишних слешей.
- 2025-10-10 · gpt-5-codex · Добавлен модуль `app.browser` с управлением процессом Playwright/Camoufox и интеграционными тестами на создание/завершение сессий.
- 2025-10-11 · gpt-5-codex · Добавлены фоновые reaper-задачи, TTL-метрики в `/health`, эндпоинт `POST /sessions/{id}/touch` и покрытие тестами.
- 2025-10-12 · gpt-5-codex · Интегрирован процессный noVNC-контроллер, расширены настройки VNC и обновлены unit-тесты с заглушками.
- 2025-10-13 · gpt-5-codex · Добавлены Prometheus-метрики, эндпоинт `/metrics` и тестовое покрытие на экспорт/счётчики.
- 2025-10-14 · gpt-5-codex · Привели код и тесты к требованиям Ruff (импорт, длины строк, ошибки) и актуализировали конфигурацию линтера.
- 2025-10-15 · gpt-5-codex · Добавлены warm pool-конфиги (JSON), загрузка при старте, новые настройки и модульные тесты на валидацию/парсинг.
- 2025-10-16 · gpt-5-codex · Реализован ``WarmPoolManager`` с управлением состояниями, recycle, преднавигацией и юнит-тестами на ключевые сценарии.
- 2025-10-17 · gpt-5-codex · Интегрирован warm pool в `SessionManager`/API, добавлен отклик 429 при нехватке слотов и покрытие тестами.
- 2025-10-18 · gpt-5-codex · Добавлены REST-эндпоинты `/workstations*`, in-memory издатель `WorkstationEvent` и интеграционные тесты API.
