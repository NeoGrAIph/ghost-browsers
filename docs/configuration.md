# Конфигурация и переменные окружения (lean)

## Общие
- `KEYCLOAK_REALM` / `KEYCLOAK_URL` / `KEYCLOAK_CLIENT_ID`

## Gateway
- `DISCOVERY_MODE` = `k8s` | `static`
- `RUNNERS` — список `host:port` при static
- `JWT_JWKS_URL` — публичный JWKS Keycloak
- `VNC_TOKEN_TTL_SEC` (<= 300)
- `GATEWAY_TRUSTED_CIDRS` — через запятую; список подсетей (IPv4/IPv6), из которых
  запросы считаются «внутренними» и не требуют аутентификации. Пример: `10.0.0.0/8,fd00::/64`.
- `GATEWAY_TRUSTED_HEADER` — (опционально) имя заголовка, который может выставлять
  ingress/sidecar для пометки доверенных вызовов. Значение проверяется на `true/1`.

## Runner
- `HTTP_PROXY`, `HTTPS_PROXY`, `SOCKS_PROXY` — индивидуальные прокси
- `START_URL`, `START_URL_WAIT_MS`, `WARMUP`
- `BROWSER_PREFS_PATH` — путь к «тумблерам» (ConfigMap/Secret)
- `CAMOUFOX_HEADLESS=virtual` (по умолчанию)
- (Опционально) `XDG_CACHE_HOME` — общий кэш, если потребуется

## UI
- `VITE_GATEWAY_URL` — базовый URL Gateway для REST/SSE (включая `POST /sessions`)

## VNC Gateway
- `GATEWAY_URL` — базовый URL для валидации токенов
- `CONNECT_TIMEOUT_MS`

> Секреты не хранятся в VCS. Используйте `.env` локально и Secret в k3s.