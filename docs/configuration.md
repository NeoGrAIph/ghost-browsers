# Конфигурация и запуск окружения

Документ описывает переменные окружения, конфигурационные файлы и порядок
подготовки локального и production окружения Ghost Browsers.

## Общие шаги
1. Скопируйте `.env.example` → `.env` и при необходимости измените значения
   (например, секреты VNC, лимит слотов runner). Значения с `:-` в
   `docker-compose.yml` имеют дефолты, поэтому `.env` можно не создавать для
   быстрого старта.【F:docker-compose.yml†L5-L58】【F:.env.example†L1-L18】
2. Установите зависимости: `make bootstrap`, `pnpm install --frozen-lockfile`,
   `poetry install --no-root` в нужных сервисах.【F:AGENTS.md†L24-L55】
3. Запустите стек: `docker compose up --build`. BuildKit соберёт образы runner,
   gateway, vnc-gateway и ui, смонтирует warm pool JSON и пробросит порты
   (`8080`, `8081`, `8082`, `8001`). Проверить готовность можно командами из
   README (curl `/health`, `/runners`, `/events`, `/metrics`).【F:docker-compose.yml†L5-L58】【F:READMI.md†L123-L152】

## Runner (`services/runner`)
Runner использует `RunnerSettings` и JSON файлы для warm pool.

- **Переменные окружения** (см. `config/settings.py`):
  - `RUNNER_ID`, `SLOT_LIMIT`, `VNC_ENABLED` — идентификатор и вместимость
    раннера; значения по умолчанию передаются из compose.
  - `WARM_POOL_CONFIG_PATH`, `BROWSER_PREFS_PATH` — пути до JSON, смонтированных в
    контейнер. Локальные примеры лежат в `services/runner/config/`.
  - `WARM_POOL_MODE` (`warm`, `cold`, `hybrid`) — стратегия распределения слотов.
  - `VNC_HTTP_BASE_URL`, `VNC_WS_BASE_URL` — базовые URL для генерации VNC
    ссылок; должны соответствовать публичному адресу `vnc-gateway`.
  - `EVENT_ENDPOINT` (опционально) — HTTP URL для публикации `SessionEvent` в
    gateway (`POST /events`).
  - Прокси (`PROXY_HTTP_BASE_URL`, `PROXY_HTTPS_BASE_URL`, `PROXY_SOCKS_BASE_URL`),
    `START_URL`, `START_URL_WAIT_MS`, `PREWARM_NAVIGATION` — опциональные
    настройки warm pool и холодных запусков.【F:services/runner/app/config/settings.py†L30-L208】
- **Конфигурационные файлы**:
  - `config/warm-pool.local.json` — список рабочих станций (`id`, `fingerprint_id`,
    `tags`, `prefs_rel_path`).
  - `config/browser-prefs.local.json` — набор профилей браузера, на которые
    ссылаются станции через `prefs_rel_path`. Эти файлы монтируются в контейнер
    как `/etc/runner/warm-pool.json` и `/etc/runner/browser-prefs.json`.
- **Smoke чек**: после запуска `curl http://localhost:8082/health` и убедитесь,
  что `warm_pool.total` совпадает с количеством станций в JSON.

## Gateway (`services/gateway`)
Gateway читает конфигурацию через `GatewaySettings.from_env`.

- `DISCOVERY_MODE` (`static`, `http`) и `DISCOVERY_ENDPOINT` — управляют
  discovery. В compose используется `static` с JSON списком `RUNNERS`.
- `RUNNERS` — JSON массив с объектами runner (`id`, `base_url`, `total_slots`,
  шаблоны VNC URL). При изменении warm pool обновляйте `total_slots` и
  `available_slots` для точной телеметрии.【F:services/gateway/app/config.py†L34-L108】
- `VNC_TOKEN_SECRET`, `VNC_TOKEN_TTL_SEC` — параметры подписи токенов для VNC.
  TTL ограничен диапазоном 1–300 секунд.
- `JWT_JWKS_URL` — JWKS документ Keycloak; локально можно оставить заглушку.
- `GATEWAY_TRUSTED_CIDRS`, `GATEWAY_TRUSTED_HEADER` — доверенные подсети и
  заголовок исходного IP, позволяющие обходить JWT для внутренних вызовов.
- `DISCOVERY_POLL_INTERVAL_SEC` — частота health-проб фоновым процессом.

После запуска убедитесь, что `curl http://localhost:8080/runners` возвращает
активный runner и что события появляются в SSE `curl -N http://localhost:8080/events`.

## VNC Gateway (`services/vnc-gateway`)
VNC gateway использует `camou_vnc_gateway.config.Settings`.

- `VNC_GATEWAY_RUNNER_HTTP_BASE` / `WS_BASE` — адреса runner внутри сети
  контейнеров (`http://runner:8080`, `ws://runner:8080`).
- `VNC_GATEWAY_TOKEN_SECRET` — должен совпадать с gateway.
- `VNC_GATEWAY_METRICS_BACKEND` — `prometheus` (по умолчанию) или `otlp`.
- `VNC_GATEWAY_METRICS_REGISTRY_IMPORT` / `OTLP_EXPORTER_IMPORT` — путь к
  кастомным экспортёрам (опционально).【F:services/vnc-gateway/app/camou_vnc_gateway/config.py†L6-L120】

Smoke: `curl http://localhost:8001/metrics` должен вернуть Prometheus payload.

## UI (`apps/ui`)
- В runtime UI использует переменную `VITE_GATEWAY_URL`; Dockerfile передаёт `/api`,
  а `nginx.conf` проксирует этот путь в gateway.【F:apps/ui/Dockerfile†L1-L23】【F:apps/ui/nginx.conf†L1-L24】
- Для локальной разработки Vite можно запустить `pnpm -C apps/ui dev -- --host` и
  задать `VITE_GATEWAY_URL=http://localhost:8080`.
- UI ожидает, что gateway доступен без дополнительного префикса (кроме `/api`
  при работе через Nginx).

## Camoufox worker (`services/camoufox_worker`)
- `WORKER_MODE` (`native`, `orchestrator`) определяет основной entrypoint.
- `GATEWAY_URL`, `GATEWAY_TOKEN`, `RUNNER_URL` — параметры доступа к control-plane.
- Образ собирается аналогично runner: Camoufox предзагружается на этапе build,
  запуск `python -m camoufox fetch` в рантайме запрещён.【F:services/camoufox_worker/AGENTS.md†L1-L33】

## Helm
Helm чарты находятся в `docs/helm/platform`. Они поддерживают передачу
переменных и секретов (`secretEnv`, `extraEnvFromSecrets`) для всех компонентов.
Перед деплоем подготовьте namespace и Secrets (`gateway-keycloak`, `gateway-vnc`,
`camoufox-credentials` и т.д.). После обновления значений проверяйте релиз
командами `helm status` и `kubectl get pods,svc,ingress`.
