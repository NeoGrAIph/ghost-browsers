# AGENT_NOTES — runner

## Overview
FastAPI-based service that manages browser sessions for Ghost Browsers. Provides in-memory lifecycle management, publishes session events, and exposes minimal HTTP endpoints for orchestration and health checks.

## Interfaces
- **HTTP**
  - `GET /health` — возвращает `{status, runner_id, camoufox_path, slots, vnc, proxy, prewarm}`;
    `slots.total` считывается из `RunnerSettings.slot_limit`, `slots.active` — количество
    не-`DEAD` сессий; `prewarm` включает счётчик и последнюю ошибку прогрева.
  - `POST /sessions` — accepts `SessionCreatePayload`, returns created `core.Session` snapshot.
  - `PATCH /sessions/{id}` — accepts `SessionUpdatePayload`, merges labels/metadata, returns updated `core.Session`.
  - `DELETE /sessions/{id}` — marks session as `DEAD`, returns terminal snapshot.
- **Event transport**
  - `SessionEventPublisher.publish(SessionEvent)` — protocol for pushing lifecycle events downstream. Default implementation stores events in memory (`InMemorySessionEventPublisher`) but can be swapped for HTTP/SSE bridges via `CallbackSessionEventPublisher`.

## Data & Models
- Uses `core.Session`, `SessionEvent`, `SessionProxySettings`, `SessionVncDetails`, and related enums.
- Local payload models (`SessionCreatePayload`, `SessionUpdatePayload`) act as request DTOs before conversion into immutable core models.
- Sessions are keyed by UUID and persisted in-memory; timestamps sourced from an injectable clock (UTC aware).
- `SessionManagerMetrics` агрегирует счётчик активных сессий и историю ошибок прогрева (bounded deque по
  `RunnerSettings.prewarm_failure_history_size`).

## Decisions
- **In-memory publisher**: Стандартный транспорт построен на `InMemorySessionEventPublisher` и считается продукционным решением; при необходимости можно оборачивать его через `CallbackSessionEventPublisher` для сторонних интеграций без отказа от in-memory ядра.
- **Automatic VNC stubs**: When sessions are non-headless and no explicit VNC payload is provided, the manager synthesises `SessionVncDetails` using configurable base URLs and bounded TTL (<=300s) to respect `SessionVncDetails` invariants. Глобальный флаг `RunnerSettings.vnc_enabled` отключает генерацию stub-значений.
- **Gateway-signed VNC tokens**: Runner never persists VNC `token` or `token_ttl_seconds`; any user-supplied values are stripped and synthetic descriptors leave them `None` so that the gateway can issue signed credentials.
- **Environment-driven settings**: `RunnerSettings.from_env` centralises configuration parsing without extra dependencies, easing future extension. Дополнительные параметры: `slot_limit`, базовые VNC URL, глобальный флаг прокси и ёмкость истории ошибок прогрева.
- **Bounded prewarm history**: менеджер хранит ошибки прогрева в `deque` с ограничением размера, что позволяет health-эндпоинту
  показывать последние сбои без риска утечки памяти.
- **Gateway proxy compatibility**: `SessionCreatePayload` остаётся публичным контрактом, но теперь вызывается через Gateway, потому важна обратная совместимость и строгая валидация.

## Constraints & Invariants
- `RunnerSettings.vnc_token_ttl_seconds` capped at 300 seconds to align with `SessionVncDetails` validation.
- `SessionManager` always updates `last_seen_at` on mutations to ensure monotonic timestamps.
- `SessionEvent` timestamps are UTC and emitted for every state change; terminal events require `SessionStatus.DEAD`.
- Session mutations occur under an `anyio.Lock` to avoid race conditions in async contexts.

## Known Gaps / TODO
- [ ] Зафиксировать профиль нагрузки для in-memory издателя после появления боевых метрик, чтобы подтвердить соответствие latency требованиям.

## How to Test
- `poetry install --no-root`
- `poetry run pytest -q` (anyio-powered unit tests)
- `poetry run ruff check .`

## Changelog (for agents)
- 2024-09-22 · OpenAI ChatGPT · Расширен `/health`, добавлены метрики/история prewarm, новые настройки и модульные тесты.
- 2025-10-05 · gpt-5-codex · Sanitised runner VNC payloads to defer token issuance to the gateway and extended unit tests.
- 2025-10-07 · gpt-5-codex · Зафиксировано использование in-memory event publisher как основного транспорта, обновлены Known Gaps.
