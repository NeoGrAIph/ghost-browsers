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
  - `GET /workstations` — возвращает `WorkstationListResponse` с массивом `WorkstationSnapshotModel` (``workstation_id``, fingerprint, proxy, state).
  - `POST /workstations/reserve` — принимает `WorkstationReservationRequest`, возвращает `WorkstationReservationResponse` (snapshot + launch env).
  - `POST /workstations/{id}/busy` — переводит слот из reserved в busy, возвращает `WorkstationActionResponse`.
  - `POST /workstations/{id}/cancel` — откатывает неудачное резервирование в idle.
  - `POST /workstations/{id}/release` — рециклирует busy слот обратно в idle и возвращает новый snapshot.
  - `POST /workstations/{id}/restart` — форсирует recycle браузера без участия сессий.
  - `POST /workstations/{id}/drain` — помечает рабочую станцию как недоступную (state=`draining`).
  - `POST /workstations/{id}/enable` — восстанавливает drained/error слот (перезапускает браузер).
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
- Дополнительно экспортируются warm-pool gauges (`runner_workstations_*`), histogram
  `runner_workstation_recycle_seconds`, summary `runner_session_allocate_seconds` и счётчики
  ошибок навигации/прокси; `WarmPoolManager` и `SessionManager` обновляют значения при смене
  состояния.
- Конфигурация пула прогретых рабочих станций описывается `WarmPoolConfig`
  (`app.config.warm_pool`). Запись (`WorkstationConfigEntry`) содержит хотя бы `id`
  (строгая уникальность, проверяется валидатором) и произвольные дополнительные поля
  (разрешены `extra`, чтобы операторы могли добавлять свои атрибуты). JSON-файл читается
  при старте через `load_warm_pool_config`, I/O и ошибки сериализации/валидации оборачиваются
  в `WarmPoolConfigError`.
- REST-роутер `app.routers.workstations` использует Pydantic-модели `WorkstationSnapshotModel`,
  `WorkstationListResponse`, `WorkstationReservationRequest/Response` и `WorkstationActionResponse`
  для документирования и сериализации warm-пула.

## Decisions
- **Container delivery pipeline**: Runner образ собирается через `make runner-image`, который использует BuildKit
  и прогоняет `poetry check`, `poetry install --with dev --no-root`, `PYTHONPATH=. poetry run pytest -q`,
  а также `python -m camoufox path` и `python -m camoufox version` внутри контейнера. GitHub Actions workflow
  `runner-image.yml` вызывает тот же таргет, пушит образ в GHCR и подписывает его `cosign` (keyless,
  `COSIGN_EXPERIMENTAL=1`).
- **In-memory publisher**: Стандартный транспорт построен на `InMemorySessionEventPublisher` и считается продукционным решением; при необходимости можно оборачивать его через `CallbackSessionEventPublisher` для сторонних интеграций без отказа от in-memory ядра.
- **HTTP publisher toggle**: `get_event_publisher` читает `RunnerSettings.event_endpoint` и, если URL задан, использует `HttpSessionEventPublisher`, публикующий события в Gateway через `POST /events`.
- **Workstation events**: `WarmPoolManager` публикует `workstation.state_changed|recycled|error` при любых переходах слота; маршруты `/workstations` только вызывают методы менеджера.
- **SSE/WS обёртки**: `SseWorkstationEventPublisher` и `WebSocketWorkstationEventPublisher` форматируют события для стриминга в Gateway/UI.
- **Camoufox SDK dependency**: Runner зависит от официального `camoufox==0.4.11[geoip]`, а локальный shim (`packages/camoufox`) лишь делегирует вызовы к нему. Тесты используют автofixture, которая подсовывает изолированный каталог установки и подменяет сетевые вызовы.
- **Process-backed VNC controller**: Non-headless sessions allocate Xvfb/x11vnc/websockify helpers via `ProcessVncController`. The controller maintains a bounded pool of displays and ports, composes public HTTP/WS URLs from `RunnerSettings`, and tears down helpers whenever sessions terminate or switch to headless mode.
- **Gateway-signed VNC tokens**: Runner never persists VNC `token` or `token_ttl_seconds`; any user-supplied values are stripped and synthetic descriptors leave them `None` so that the gateway can issue signed credentials.
- **Environment-driven settings**: `RunnerSettings.from_env` centralises configuration parsing without extra dependencies, easing future extension. Дополнительные параметры: `slot_limit`, базовые VNC URL, глобальный флаг прокси и ёмкость истории ошибок прогрева.
- **Local compose warm pool park**: docker-compose mounts `services/runner/config/warm-pool.local.json` и `browser-prefs.local.json`, обеспечивая демонстрационный парк рабочих станций с фиксированными `fingerprint_id` и набором тумблеров, который разделяют прогретые и холодные сессии; режим по умолчанию `WARM_POOL_MODE=hybrid` даёт возможность создавать холодные браузеры, когда парк занят.
- **Bounded prewarm history**: менеджер хранит ошибки прогрева в `deque` с ограничением размера, что позволяет health-эндпоинту
  показывать последние сбои без риска утечки памяти.
- **Container image**: Runner контейнер собирается из `mcr.microsoft.com/playwright/python` (1.55.0-noble), использует Poetry для in-project виртуального окружения под учёткой `pwuser`, устанавливает production wheel `camoufox[geoip]==0.4.11`, прогружает артефакты Camoufox во время сборки, удаляет локальные stub-пакеты из образа и монтирует BuildKit-кеши для Poetry/pip. Образ стал толстым: в нём предустановлены локали, Windows-совместимые шрифты (Segoe UI/Calibri и т.п.), системные наборы шрифтов, Xvfb/x11vnc/websockify/noVNC и вспомогательные CLI (curl/ffmpeg/jq), поэтому headless и VNC-процессы работают без дополнительных зависимостей.
- **Warm pool-backed sessions**: `SessionManager` теперь зависит от `WarmPoolManager`, резервирует слот до создания сессии и
  рециклирует его при завершении. В случае исчерпания слотов API возвращает 429.
- **Warm pool strategy modes**: `RunnerSettings.warm_pool_mode` позволяет выбирать между
  тёплыми слотами, холодными запусками и гибридом; `SessionManager` автоматически
  переключается на `launch_browser`, если гибридный режим не находит idle-слота, и
  добавляет в метаданные `browser_origin` с деталями источника.
- **Browser flags propagation**: `RunnerSettings.browser_required_flags` и модуль
  `app.browser_flags` нормализуют флаги из конфигурации и метаданных; warm pool
  запускает браузеры с обязательными переменными окружения, а `SessionManager`
  инжектирует их в холодные старты и откатывается на cold launch, если запрос
  требует дополнительных флагов, несовместимых с текущими warm-слотами.
- **Gateway proxy compatibility**: `SessionCreatePayload` остаётся публичным контрактом, но теперь вызывается через Gateway, потому важна обратная совместимость и строгая валидация.
- **Helm deployment**: общий чарт `docs/helm/platform` разворачивает Runner вместе с Gateway/VNC/UI, позволяет прокидывать переменные
  окружения и секреты (`secretEnv`, `extraEnvFromSecrets`) для токенов Camoufox, прокси и warm-pool конфигураций.
- **Playwright launch lifecycle**: `app.browser.launch_browser` стартует Playwright в режиме `launch-server`, сохраняет `wsEndpoint`/PID в метаданных и позволяет `SessionManager` останавливать процесс при переходе в `DEAD` или очистке endpoint. Исключения при старте выполняют откат без публикации событий.
- **Idle TTL reaper**: `SessionManager` содержит AnyIO-based reaper, который вызывает
  `reap_expired_sessions`, завершает истёкшие по `idle_ttl_seconds` сессии и публикует события
  `session.ended` с reason=`idle-timeout`. Запускается/останавливается через `start()`/`stop()` и
  lifecycle-хуки FastAPI.
- **Prometheus registry**: Runner экспортирует `/metrics`, используя
  `prometheus_client.CollectorRegistry`; значения обновляются в момент изменения состояния
  (`active_sessions`, VNC аллокации, пробеги reaper-а) вместо ленивой агрегации на запрос.
- **Structured logging defaults**: `app.logging.configure_logging()` обеспечивает единый формат
  логов и гарантирует наличие полей `session_id`, `workstation_id`, `fingerprint_id` даже при
  отсутствии значений в `extra`.
- **JSON-конфиг пула прогрева**: Дополнительные параметры окружения (`WARM_POOL_CONFIG_PATH`,
  `BROWSER_PREFS_PATH`, `PREWARM_NAVIGATION`, `START_URL`, `START_URL_WAIT_MS`) разбираются в
  `RunnerSettings`. Отдельный JSON-файл описывает warm pool; при ошибках чтения/валидации
  старт завершается с развёрнутым сообщением, что упрощает операционную диагностику.
- **Warm pool state machine**: ``WarmPoolManager`` использует явные состояния (`idle → reserved → busy → recycling`, а также `draining`/`error`) и индивидуальные ``asyncio.Lock`` для каждой рабочей станции. Это предотвращает гонки при параллельных резервациях и гарантирует, что recycle всегда закрывает процесс, чистит профили и перезапускает Camoufox с тем же fingerprint.
- **Session recovery endpoint**: Runner публикует `GET /sessions`, который отдаёт `SessionManager.list_sessions` для восстановления состояния control-plane сервисов (gateway, worker) после рестартов. Контракт покрыт юнит-тестами `test_list_sessions_returns_empty_collection` и `test_list_sessions_returns_active_sessions`.

## Constraints & Invariants
- `RunnerSettings.vnc_token_ttl_seconds` capped at 300 seconds to align with `SessionVncDetails` validation.
- `SessionManager` always updates `last_seen_at` on mutations to ensure monotonic timestamps.
- `SessionEvent` timestamps are UTC and emitted for every state change; terminal events require `SessionStatus.DEAD`.
- Session mutations occur under an `anyio.Lock` to avoid race conditions in async contexts.
- Нагрузочный тест издателя подтверждает, что 10 параллельных продюсеров (10k событий) удерживают publish avg ≤ 20 мс, peak ≤ 100 мс, а drain ≤ 200 мс (pytest `test_inmemory_publisher_drain_latency_under_parallel_load`).
- Health payload normalises proxy base URLs by stripping trailing slashes
  only when the configured path is empty, preserving operator-provided
  values.
- Idle reaper использует инъецируемые часы и общее состояние `SessionManager`; пересчёт ближайшего TTL выполняется после любых
  апдейтов/завершений, чтобы метрики `next_expiry_at`/`reaper` оставались консистентными.
- Взаимодействие с Gateway/SSE происходит только внутри доверенной сети кластера; авторизация на уровне HTTP не ожидается,
  вместо этого требуется сетевое разделение и настройка доверенных CIDR на стороне Gateway.
- Доступность VNC зависит от бинарей `Xvfb`, `x11vnc` и `websockify`; при их отсутствии `ProcessVncController` отключается и сессии остаются без VNC-URL.
- Docker-образ предполагает запуск под `pwuser`, PATH включает `.venv/bin`, а контекст сборки обязан содержать каталоги `camoufox` и `packages`, иначе Poetry не найдёт path-зависимости.

## Known Gaps / TODO
- [x] Зафиксирован профиль нагрузки для in-memory издателя: 10k событий (10 параллельных продюсеров) удерживают publish avg ≤ 20 мс, peak ≤ 100 мс, drain ≤ 200 мс (см. `test_inmemory_publisher_drain_latency_under_parallel_load`).
- [x] Документирован поток восстановления: gateway опрашивает `GET /sessions` на старте (см. `test_lifespan_restores_sessions_from_healthy_runners`), runner покрыт тестами `test_list_sessions_returns_*`.

## How to Test
- `poetry install --no-root`
- `poetry run pytest -q` (anyio-powered unit tests)
- `poetry run ruff check .`
- `make runner-image` — соберёт контейнер, выполнит `poetry check`, `poetry install --with dev --no-root`, `PYTHONPATH=. poetry run pytest -q`, `python -m camoufox path` и `python -m camoufox version` внутри образа.
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_config_warm_pool.py -q`
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_warm_pool.py -q`
- Таргетно: `PYTHONPATH=. poetry run pytest services/runner/tests/test_workstations_api.py -q`
- `docker build -f services/runner/Dockerfile -t ghost-runner:latest .`

## Changelog (for agents)
- 2024-09-22 · OpenAI ChatGPT · Расширен `/health`, добавлены метрики/история prewarm, новые настройки и модульные тесты.
- 2025-10-03 · gpt-5-codex · Добавлен Dockerfile на базе Playwright-образа, Poetry-инсталляция зависимостей и `.dockerignore` для сборки runner внутри контейнера без выполнения `camoufox fetch`.
- 2025-10-03 · gpt-5-codex · Подготовлены Helm-шаблоны и образцы values для Runner (секреты Camoufox/прокси, ресурсы) и обновлена документация по деплою.
- 2025-10-05 · gpt-5-codex · Sanitised runner VNC payloads to defer token issuance to the gateway and extended unit tests.
- 2025-10-07 · gpt-5-codex · Зафиксировано использование in-memory event publisher как основного транспорта, обновлены Known Gaps.
- 2025-10-08 · gpt-5-codex · Добавлен HTTP publisher (`POST /events`) и покрытие unit-тестами + конфиг-переключатель в зависимостях.
- 2025-10-09 · gpt-5-codex · Переключили зависимость `camoufox` на локальный stub-пакет и нормализовали выдачу proxy URL в `/health`,
  чтобы `poetry install` и unit-тесты проходили в офлайн-окружении без лишних слешей.
- 2025-10-25 · ChatGPT · Перешли на официальный SDK Camoufox с тестовыми двойниками (фикстура для подмены установки, обновлённые smoke-скрипты, pin версии `0.4.11[geoip]`).
- 2025-10-10 · gpt-5-codex · Добавлен модуль `app.browser` с управлением процессом Playwright/Camoufox и интеграционными тестами на создание/завершение сессий.
- 2025-10-11 · gpt-5-codex · Добавлены фоновые reaper-задачи, TTL-метрики в `/health`, эндпоинт `POST /sessions/{id}/touch` и покрытие тестами.
- 2025-10-12 · gpt-5-codex · Интегрирован процессный noVNC-контроллер, расширены настройки VNC и обновлены unit-тесты с заглушками.
- 2025-10-13 · gpt-5-codex · Добавлены Prometheus-метрики, эндпоинт `/metrics` и тестовое покрытие на экспорт/счётчики.
- 2025-10-14 · gpt-5-codex · Привели код и тесты к требованиям Ruff (импорт, длины строк, ошибки) и актуализировали конфигурацию линтера.
- 2025-10-15 · gpt-5-codex · Добавлены warm pool-конфиги (JSON), загрузка при старте, новые настройки и модульные тесты на валидацию/парсинг.
- 2025-10-16 · gpt-5-codex · Реализован ``WarmPoolManager`` с управлением состояниями, recycle, преднавигацией и юнит-тестами на ключевые сценарии.
- 2025-10-17 · gpt-5-codex · Интегрирован warm pool в `SessionManager`/API, добавлен отклик 429 при нехватке слотов и покрытие тестами.
- 2025-10-18 · gpt-5-codex · Добавлены REST-эндпоинты `/workstations*`, in-memory издатель `WorkstationEvent` и интеграционные тесты API.
- 2025-10-19 · gpt-5-codex · Вынесены маршруты `/workstations` в отдельный роутер с Pydantic-моделями, WarmPoolManager публикует события state/error/recycled, добавлены SSE/WS-обёртки и интеграционные тесты.
- 2025-10-20 · gpt-5-codex · Добавлены warm-pool метрики/таймеры, расширен `/health` данными пула и настроен формат логов с идентификаторами; обновлены тесты `/metrics` и `/health`.
- 2025-10-21 · gpt-5-codex · Реализованы режимы warm pool (warm-only/cold-only/hybrid), гибридный fallback на `launch_browser`, расширение метаданных `browser_origin` и покрытие тестами.
- 2025-10-22 · gpt-5-codex · Добавлен `GET /sessions` для восстановления состояния gateway и юнит-тесты на пустой и заполненный реестры.
- 2025-10-24 · gpt-5-codex · Добавлен стресс-тест in-memory издателя (10k событий) и задокументированы пороги publish/drain.
- 2025-10-25 · gpt-5-codex · Dockerfile переключён на production `camoufox[geoip]==0.4.11` с прогревом артефактов на сборке,
  добавлены BuildKit-кеши, расширен `.dockerignore`, README-TASK дополнен инструкциями по сборке/запуску.
- 2025-10-27 · gpt-5-codex · Добавлен make-таргет/CI-контур для сборки runner-образа с контейнерными тестами и подписями cosign.
- 2025-10-28 · gpt-5-codex · Документирован локальный парк прогретых рабочих станций и примеры конфигов для docker compose.
- 2025-10-29 · gpt-5-codex · Перевели docker compose на гибридный режим тёплого пула, чтобы локально запускались холодные сессии при исчерпании парка.
- 2025-10-30 · gpt-5-codex · Добавлены pytest-конфигурации для автоматического импорта пакета `app` и задан `PYTHONPATH` внутри контейнера Runner, чтобы `uvicorn` и тесты работали без ручных переменных окружения.
- 2025-10-31 · gpt-5-codex · Добавлена поддержка обязательных/запросных browser flags в cold launch и warm pool, нормализация значений и тесты на совместимость режимов.
- 2025-10-31 · gpt-5-codex · Docker-образ расширен системными шрифтами, Windows-наборами, локалями и VNC-бинарями (Xvfb/x11vnc/websockify/noVNC) при сохранении поэтапной установки зависимостей через Poetry.
