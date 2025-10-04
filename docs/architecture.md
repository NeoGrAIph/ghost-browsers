# Ghost Browsers — Архитектурный обзор

## Общее описание
Ghost Browsers управляет жизненным циклом одноразовых Camoufox-сессий и предоставляет
операторам UI, REST/SSE/WS API и защищённый доступ к VNC. Контрол-плейн состоит
из трёх FastAPI сервисов и SPA:

- **Runner** отвечает за запуск браузеров, warm pool прогретых рабочих станций,
  оркестрацию VNC пайплайна и публикацию событий жизненного цикла сессий. Логика
  сосредоточена в `SessionManager`, `WarmPoolManager` и `ProcessVncController`,
  объединённых через FastAPI в `app.main`.【F:services/runner/app/session_manager.py†L35-L224】【F:services/runner/app/main.py†L21-L128】
- **Gateway** выступает публичным фасадом: реализует REST/SSE/WS API, проверяет
  JWT через JWKS, выпускает токены VNC и хранит in-memory реестры раннеров и
  сессий. Фоновый цикл отслеживает здоровье раннеров и синхронизирует состояние
  при рестартах.【F:services/gateway/app/main.py†L24-L123】
- **VNC Gateway** валидирует короткоживущие токены и проксирует HTTP/WebSocket
  трафик к runner, собирая метрики по активным подключениям.【F:services/vnc-gateway/app/camou_vnc_gateway/routes.py†L1-L118】
- **UI** (React + Vite) визуализирует раннеры, warm pool и сессии, подписывается
  на SSE-поток событий и открывает VNC iframe через токенизированные URL.

## Ключевые компоненты
### Runner
Runner разворачивается из `services/runner/Dockerfile` на базе Playwright. На
старте FastAPI приложение конфигурируется через `RunnerSettings`, подготавливает
warm pool из JSON (`WarmPoolConfig`) и запускает `SessionManager` в lifespan.

`SessionManager` хранит активные сессии, публикует события (`SessionEvent`),
запускает idle reaper и инкрементирует Prometheus метрики. При создании сессии
он резервирует warm slot (если доступен), запускает Camoufox (cold) и
предоставляет VNC детали через `ProcessVncController`. Метрики и warm pool
статистика попадают в `/health` и `/metrics` для мониторинга.【F:services/runner/app/session_manager.py†L35-L369】【F:services/runner/app/main.py†L56-L122】

### Gateway
Gateway использует `GatewaySettings` для чтения переменных окружения (`RUNNERS`,
`DISCOVERY_MODE`, `VNC_TOKEN_SECRET`, `GATEWAY_TRUSTED_CIDRS` и др.) и создаёт
приложение через фабрику `create_app`. Он хранит:

- `SessionRegistry` и `RunnerRegistry` (in-memory),
- `InMemorySessionEventBridge` для SSE/WS,
- `RunnerDiscoveryService` + фоновую задачу для health-чеков,
- `VncTokenService` для подписи HMAC JWT токенов.

REST/SSE/WS маршруты расположены в `routers/` (sessions, runners, events,
workstations). Lifespan восстанавливает активные сессии через `RunnerCommandClient`
и выполняет регулярные health-чек запросы к `/health` runner'ов. Токены VNC
встраиваются в публичные URL, а доверенные CIDR/заголовки позволяют пропускать
внутренние вызовы без JWT.【F:services/gateway/app/config.py†L12-L130】【F:services/gateway/app/services/runner_ws_proxy.py†L1-L129】

### VNC Gateway
Сервис `camou_vnc_gateway` инициализирует конфигурацию (`Settings`), токен-
валидатор и прокси к runner (`RunnerProxy`).

- `GET /sessions/{id}` — проксирует HTTP трафик после проверки токена;
- `WS /sessions/{id}/ws` — двунаправленный прокси WebSocket с валидацией;
- `GET /metrics` — отдаёт Prometheus payload из локального реестра.

Метрики учитывают успешные/неуспешные проверки токена и количество активных
подключений (HTTP/WS). Токены должны совпадать с секретом, который использует
Gateway.【F:services/vnc-gateway/app/camou_vnc_gateway/token.py†L1-L129】【F:services/vnc-gateway/app/camou_vnc_gateway/metrics.py†L1-L146】

### UI
UI собирается Vite'ом и поставляется через Nginx (`apps/ui/Dockerfile`).
Внутренний `nginx.conf` проксирует `/api/` в gateway, поэтому приложение
взаимодействует с REST/SSE без отдельной настройки CORS. Основные блоки:

- `src/api` — REST клиенты и SSE подписка (`createEventSource`).
- `src/store` — Zustand сторы сессий/раннеров/воркстейшенов.
- `src/components/VncViewer` — iframe/noVNC интеграция для токенизированных URL.

### Camoufox Worker
Worker поставляет CLI и фоновые задачи (health, warmup) для запуска вне
контрол-плейна. Он переиспользует shim `packages/camoufox`, проверяет наличие
бинарей и умеет обращаться к gateway/runner по токену. Smoke-скрипт `smoke.py`
используется при сборке образа и локальной проверке.

## Зоны доверия и безопасность
- **Внутренний кластер**: трафик между gateway, runner и vnc-gateway считается
  доверенным. Gateway поддерживает список доверенных CIDR и заголовок
  переадресации (`GATEWAY_TRUSTED_HEADER`), чтобы обходить JWT внутри кластера.【F:services/gateway/app/config.py†L60-L127】
- **Публичный периметр**: UI и внешние клиенты обязаны использовать Keycloak JWT
  (через JWKS). VNC токены — короткоживущие HMAC JWT (< 300 секунд).
- **Секреты**: `VNC_TOKEN_SECRET` должен совпадать в gateway и vnc-gateway, токены
  Camoufox/Keycloak держатся в Secret/`.env`.

## Потоки данных
1. Клиент вызывает `POST /sessions` на gateway. Сервис выбирает раннер (по
   `RunnerRegistry`), проксирует запрос `SessionCreatePayload` и сохраняет
   результат в `SessionRegistry`.
2. Runner создаёт/обновляет `Session`, публикует `SessionEvent` через bridge и
   возвращает VNC/WS детали.【F:services/runner/app/session_manager.py†L196-L369】
3. Gateway обогащает ответ VNC токеном, пересылает событие в SSE/WS и обновляет
   in-memory реестр.
4. UI/интеграции получают события через `GET /events` или `WS /events/ws`, а VNC
   iframe использует `vnc-gateway` с токеном.
5. Idle reaper runner'а закрывает просроченные сессии; gateway удаляет их из
   реестров при следующем health-чеке.

## Нефункциональные требования
- Быстрый старт warm сессии (≤ 4 секунд) достигается за счёт прогретого пула и
  отсутствия внешних сетевых вызовов при создании.
- Метрики Prometheus доступны на `/metrics` runner и vnc-gateway; gateway можно
  интегрировать с внешним мониторингом через `SessionEvent` поток и health API.
- Контейнеры собираются reproducible: Dockerfile runner предзагружает Camoufox,
  gateway использует Poetry с локальным venv, UI — детерминированный `pnpm build`.

## Локальный стек
`docker-compose.yml` поднимает все компоненты для интеграционного теста. Runner
получает конфиги warm pool из `services/runner/config/*.json`; gateway и
vnc-gateway разделяют `VNC_TOKEN_SECRET`. UI доступен на `http://localhost:8081`,
API — `http://localhost:8080` и `/api` за обратным прокси.
