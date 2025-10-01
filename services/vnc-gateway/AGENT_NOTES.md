# AGENT_NOTES — vnc-gateway

## Overview
FastAPI service that validates short-lived VNC access tokens and proxies HTTP/WS traffic from the public Gateway to the Runner instances.

## Interfaces
- `GET /sessions/{session_id}` — requires `X-VNC-Token` header; proxies to Runner HTTP API.
- `WS /sessions/{session_id}/ws` — expects `X-VNC-Token` header; establishes bidirectional tunnel to Runner websocket endpoint.

## Data & Models
- `Settings` (`app/camou_vnc_gateway/config.py`): environment-driven configuration using `pydantic-settings`. Includes runner HTTP/WS base URLs and shared token secret.
- `TokenValidator`: валидирует HS256 JWT с claim'ами `sid`, `exp`, `iss`, `sub`, подписанные общим секретом с Gateway.

## Decisions
- Токены — стандартные HS256 JWT; валидация выполняется через `python-jose` с проверкой `iss`, `exp` и `sid`.
- Connection metrics backed by in-memory `ConnectionRegistry` with async context manager; logs `connection.started/finished` events.
- WebSocket proxy implemented via `websockets` library using two relay tasks; HTTP proxy leverages a shared `httpx.AsyncClient` for outbound requests.
- Dependency wiring relies on `typing.Annotated` wrappers to avoid Ruff `B008` violations while keeping FastAPI semantics.
- Tests inject stubbed `RunnerProxy` via dependency overrides; `tests/conftest.py` adjusts `sys.path` instead of installing the package.
- Runner proxy keeps a singleton `httpx.AsyncClient` and resolves `target_port` from query/referer/cookie (persisting it via `vnc-target-port` cookie) to build Runner URLs with configurable prefixes, mirroring the upstream beta implementation. WebSocket relaying now mirrors the production gateway behaviour with `FIRST_EXCEPTION` waiting semantics and graceful close codes (1008/1011).
- WebSocket relay now enforces explicit open/idle/send timeouts and relies on a bounded upstream frame queue (`max_queue=16`) to ensure backpressure, closing client connections with 1011 on timeout or network failures.

## Constraints & Invariants
- Tokens must include the matching session identifier; mismatches immediately rejected.
- Only `ws`/`wss` schemes accepted for Runner WS base; HTTP base limited to `http/https`.
- `ConnectionRegistry` is process-local and not durable; acceptable for current scope.
- Сервис остаётся частью публичного периметра: проверка VNC-токена обязательна даже для запросов,
  поступающих из кластера. Беспарольный режим распространяется только на REST/SSE/WS Gateway.

## Known Gaps / TODO
- [ ] Replace manual websocket proxy with production-ready solution once Runner API stabilises (e.g. uvicorn websockets integration).
- [ ] Integrate metrics registry with Prometheus/OpenTelemetry backend when available.
- [ ] Harden token validator against replay (нужен учёт `iat`/одноразовых токенов поверх проверки истечения).

## How to Test
```bash
cd services/vnc-gateway
poetry install --no-root
poetry run ruff check .
poetry run pytest -q
```

## Changelog (for agents)
- 2025-02-14 · gpt-5-codex · Initial FastAPI service implementation with token validator, proxy wiring, and unit tests.
- 2025-10-03 · gpt-5-codex · Переведён валидатор на HS256 JWT и синхронизирован с Gateway `VncTokenService`.
- 2025-10-06 · gpt-5-codex · Синхронизирован HTTP/WS-прокси с beta-референсом: общий `httpx.AsyncClient`, выбор `target_port` из query/referer/cookie с cookie-фолбэком, обновлённая двунаправленная WebSocket-переадресация и unit-тесты на таргет-порт хелперы.
- 2025-10-08 · gpt-5-codex · Добавлены тайм-ауты/бэктрэш для WS-прокси, интеграция с `WebSocketState` и новые юнит-тесты на счастливый путь, ошибки сети и коды закрытия 1008/1011.
