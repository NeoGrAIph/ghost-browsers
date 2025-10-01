# Gateway Service

FastAPI-based edge service exposing REST, Server-Sent Events, and WebSocket
interfaces for managing runner-backed browser sessions. The gateway acts as the
public API facade and issues short-lived VNC access tokens on top of
Keycloak-protected endpoints.

## Configuration

| Variable            | Description                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `DISCOVERY_MODE`    | Runner discovery strategy (`static` by default).                   |
| `DISCOVERY_ENDPOINT` | HTTP endpoint returning the runner catalog when using `http` discovery. |
| `DISCOVERY_POLL_INTERVAL_SEC` | Interval between discovery and health maintenance iterations (default `10`). |
| `RUNNERS`           | JSON-массив с объектами `Runner` (см. `packages/core`).            |
| `JWT_JWKS_URL`      | URL JWKS-документа Keycloak.                                       |
| `VNC_TOKEN_TTL_SEC` | Время жизни VNC JWT (≤300 секунд).                                 |
| `VNC_TOKEN_SECRET`  | Общий HMAC-секрет для подписания VNC JWT (делится с VNC Gateway).  |

## Endpoints

- `POST /sessions` — register a session and enrich VNC details with a short-lived token.
- `GET /sessions` / `GET /sessions/{id}` — inspect active sessions.
- `POST /sessions/{id}/proxy` — update proxy configuration (`SessionProxySettings`).
- `POST /sessions/{id}/touch` — refresh `last_seen_at` heartbeat timestamp.
- `DELETE /sessions/{id}` — remove a session from the registry.
- `WS /sessions/{id}/ws` — authenticated WebSocket tunnel proxied to the runner's Playwright endpoint.
- `GET /runners` — list known runners.
- `GET /events` — Server-Sent Events stream of `SessionEvent` objects.
- `WS /events/ws` — WebSocket stream with the same event payloads.

All HTTP endpoints require a valid Keycloak bearer token. The WebSocket endpoint
expects the token either in the `Authorization: Bearer` header or in the
`token` query parameter.

## Development

```bash
cd services/gateway
poetry install --no-root
poetry run pytest -q
```

Use `poetry run ruff check .` for linting the service codebase.
