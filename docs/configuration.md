# Конфигурация и переменные окружения (lean)

## Общие
- `KEYCLOAK_REALM` / `KEYCLOAK_URL` / `KEYCLOAK_CLIENT_ID`

## Gateway
- `DISCOVERY_MODE` = `k8s` | `static`
- `RUNNERS` — список `host:port` при static
- `JWT_JWKS_URL` — публичный JWKS Keycloak
- `VNC_TOKEN_TTL_SEC` (<= 300)

## Runner
- `HTTP_PROXY`, `HTTPS_PROXY`, `SOCKS_PROXY` — индивидуальные прокси
- `START_URL`, `START_URL_WAIT_MS`, `WARMUP`
- `BROWSER_PREFS_PATH` — путь к «тумблерам» (ConfigMap/Secret)
- `CAMOUFOX_HEADLESS=virtual` (по умолчанию)
- (Опционально) `XDG_CACHE_HOME` — общий кэш, если потребуется

## VNC Gateway
- `GATEWAY_URL` — базовый URL для валидации токенов
- `CONNECT_TIMEOUT_MS`

> Секреты не хранятся в VCS. Используйте `.env` локально и Secret в k3s.