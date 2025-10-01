# AGENT_NOTES — runner

## Overview
FastAPI-based service that manages browser sessions for Ghost Browsers. Provides in-memory lifecycle management, publishes session events, and exposes minimal HTTP endpoints for orchestration and health checks.

## Interfaces
- **HTTP**
  - `GET /health` — returns `{status, runner_id, camoufox_path}` for readiness probes.
  - `POST /sessions` — accepts `SessionCreatePayload`, returns created `core.Session` snapshot.
  - `PATCH /sessions/{id}` — accepts `SessionUpdatePayload`, merges labels/metadata, returns updated `core.Session`.
  - `DELETE /sessions/{id}` — marks session as `DEAD`, returns terminal snapshot.
- **Event transport**
  - `SessionEventPublisher.publish(SessionEvent)` — protocol for pushing lifecycle events downstream. Default implementation stores events in memory (`InMemorySessionEventPublisher`) but can be swapped for HTTP/SSE bridges via `CallbackSessionEventPublisher`.

## Data & Models
- Uses `core.Session`, `SessionEvent`, `SessionProxySettings`, `SessionVncDetails`, and related enums.
- Local payload models (`SessionCreatePayload`, `SessionUpdatePayload`) act as request DTOs before conversion into immutable core models.
- Sessions are keyed by UUID and persisted in-memory; timestamps sourced from an injectable clock (UTC aware).

## Decisions
- **In-memory publisher stub**: We expose a `SessionEventPublisher` protocol with an in-memory default to unblock tests until a real transport (HTTP/SSE) is integrated.
- **Automatic VNC stubs**: When sessions are non-headless and no explicit VNC payload is provided, the manager synthesises `SessionVncDetails` using configurable base URLs and bounded TTL (<=300s) to respect `SessionVncDetails` invariants.
- **Environment-driven settings**: `RunnerSettings.from_env` centralises configuration parsing without extra dependencies, easing future extension.

## Constraints & Invariants
- `RunnerSettings.vnc_token_ttl_seconds` capped at 300 seconds to align with `SessionVncDetails` validation.
- `SessionManager` always updates `last_seen_at` on mutations to ensure monotonic timestamps.
- `SessionEvent` timestamps are UTC and emitted for every state change; terminal events require `SessionStatus.DEAD`.
- Session mutations occur under an `anyio.Lock` to avoid race conditions in async contexts.

## Known Gaps / TODO
- [ ] Replace in-memory publisher with HTTP/SSE integration towards Gateway when endpoint contract is defined.
- [ ] Enrich `/health` with slot/VNC diagnostics once browser integration lands.

## How to Test
- `poetry install --no-root`
- `poetry run pytest -q` (anyio-powered unit tests)
- `poetry run ruff check .`

## Changelog (for agents)
- 2024-09-21 · OpenAI ChatGPT · Initial FastAPI skeleton, in-memory session manager with event publishing, unit tests, and documentation update.
