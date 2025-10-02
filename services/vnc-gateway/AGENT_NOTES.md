# AGENT_NOTES — vnc-gateway

## Overview
FastAPI service that validates short-lived VNC access tokens and proxies HTTP/WS traffic from the public Gateway to the Runner instances.

## Interfaces
- `GET /sessions/{session_id}` — requires `X-VNC-Token` header; proxies to Runner HTTP API.
- `WS /sessions/{session_id}/ws` — expects `X-VNC-Token` header; establishes bidirectional tunnel to Runner websocket endpoint.
- `GET /metrics` — Prometheus exposition endpoint (text format, default registry).

## Data & Models
- `Settings` (`app/camou_vnc_gateway/config.py`): environment-driven configuration using `pydantic-settings`. Includes runner HTTP/WS base URLs and shared token secret.
- `TokenValidator`: валидирует HS256 JWT с claim'ами `sid`, `exp`, `iss`, `sub`; хранит in-memory кэш `(nonce, iat)` для защиты от повторного использования токенов (per-session `OrderedDict` с лимитом и учётом TTL).
- `metrics` (`app/camou_vnc_gateway/metrics.py`): инициализирует отдельный `CollectorRegistry`, gauge/ counter для соединений (`camou_vnc_gateway_active_connections`, `camou_vnc_gateway_connection_opens_total`) и counter `camou_vnc_gateway_token_validation_failures_total`.

- Токены — стандартные HS256 JWT; валидация выполняется через `python-jose` с проверкой `iss`, `exp`, `sid` и `iat`, после чего nonce/`iat` попадает в кэш чтобы предотвращать replay.
- Connection metrics backed by in-memory `ConnectionRegistry` with async context manager; логируем события и одновременно обновляем Prometheus-gauge/counter в собственном registry.
- WebSocket proxy теперь использует `uvicorn`-совместимый backend (`websockets.connect` + `asyncio.TaskGroup`) вместо ручного релея: two tasks pump with idle/send timeouts и повторно используют production defaults (`open_timeout`, `max_queue`, `ping_interval=None`).
- Dependency wiring relies on `typing.Annotated` wrappers to avoid Ruff `B008` violations while keeping FastAPI semantics.
- Tests inject stubbed `RunnerProxy` via dependency overrides; `tests/conftest.py` adjusts `sys.path` instead of installing the package.
- Runner proxy keeps a singleton `httpx.AsyncClient` and resolves `target_port` from query/referer/cookie (persisting it via `vnc-target-port` cookie) to build Runner URLs with configurable prefixes; WebSocket relay теперь ждёт оба направления через `TaskGroup`, отдаёт 1008 при невалидном `target_port` и 1011 при timeouts/сетевых ошибках.
- Prometheus экспозиция реализована через `/metrics`, чтобы scrape-еры (Prometheus, VictoriaMetrics и т.д.) могли использовать стандартный текстовый формат без дополнительных middleware.

## Constraints & Invariants
- Tokens must include the matching session identifier; mismatches immediately rejected.
- `iat` допускает максимум `clock_skew_tolerance_seconds` (10 секунд) относительно сервера; reuse токена до истечения TTL запрещён.
- Only `ws`/`wss` schemes accepted for Runner WS base; HTTP base limited to `http/https`.
- `ConnectionRegistry` is process-local and not durable; acceptable for current scope. Gauge удаляется после закрытия последнего соединения, чтобы не накапливать пустые time-series.
- Сервис остаётся частью публичного периметра: проверка VNC-токена обязательна даже для запросов,
  поступающих из кластера. Беспарольный режим распространяется только на REST/SSE/WS Gateway.
- `/metrics` рассчитан на scrape раз в ≤30s; registry in-memory, поэтому при перезапуске значения счётчиков обнуляются.

## Known Gaps / TODO
- [x] Replace manual websocket proxy with production-ready solution once Runner API stabilises (e.g. uvicorn websockets integration). (Done in this iteration.)
- [ ] Integrate metrics registry with Prometheus/OpenTelemetry backend when available.
- [x] Harden token validator against replay (нужен учёт `iat`/одноразовых токенов поверх проверки истечения). (Implemented in-memory nonce/`iat` cache.)

## How to Test
```bash
cd services/vnc-gateway
poetry install --no-root
poetry run ruff check .
poetry run pytest -q
```

- 2025-10-09 · gpt-5-codex · Переписан WS-прокси на uvicorn/websockets `TaskGroup`-relay, добавлены интеграционные тесты с real сервером, внедрён Prometheus `/metrics` (active/total connections, token failures), расширен `TokenValidator` (nonce/iat cache) и документирован сценарий предотвращения replay.
