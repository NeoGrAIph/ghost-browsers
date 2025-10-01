# AGENT_NOTES — vnc-gateway

## Overview
FastAPI service that validates short-lived VNC access tokens and proxies HTTP/WS traffic from the public Gateway to the Runner instances.

## Interfaces
- `GET /sessions/{session_id}` — requires `X-VNC-Token` header; proxies to Runner HTTP API.
- `WS /sessions/{session_id}/ws` — expects `X-VNC-Token` header; establishes bidirectional tunnel to Runner websocket endpoint.

## Data & Models
- `Settings` (`app/camou_vnc_gateway/config.py`): environment-driven configuration using `pydantic-settings`. Includes runner HTTP/WS base URLs and shared token secret.
- `TokenValidator`: issues/validates Base64-encoded `{session}:{hmac}` tokens with HMAC-SHA256 signatures.

## Decisions
- Token format implemented as `base64url(session_id:signature)` to keep validation deterministic without external dependencies.
- Connection metrics backed by in-memory `ConnectionRegistry` with async context manager; logs `connection.started/finished` events.
- WebSocket proxy implemented via `websockets` library using two relay tasks; HTTP proxy uses `httpx.AsyncClient` streaming API.
- Dependency wiring relies on `typing.Annotated` wrappers to avoid Ruff `B008` violations while keeping FastAPI semantics.
- Tests inject stubbed `RunnerProxy` via dependency overrides; `tests/conftest.py` adjusts `sys.path` instead of installing the package.

## Constraints & Invariants
- Tokens must include the matching session identifier; mismatches immediately rejected.
- Only `ws`/`wss` schemes accepted for Runner WS base; HTTP base limited to `http/https`.
- `ConnectionRegistry` is process-local and not durable; acceptable for current scope.

## Known Gaps / TODO
- [ ] Replace manual websocket proxy with production-ready solution once Runner API stabilises (e.g. uvicorn websockets integration).
- [ ] Integrate metrics registry with Prometheus/OpenTelemetry backend when available.
- [ ] Harden token validator against replay (needs issued-at/expiry semantics from Gateway).

## How to Test
```bash
cd services/vnc-gateway
poetry install --no-root
poetry run ruff check .
poetry run pytest -q
```

## Changelog (for agents)
- 2025-02-14 · gpt-5-codex · Initial FastAPI service implementation with token validator, proxy wiring, and unit tests.
