# AGENT_NOTES — gateway

## Overview
- FastAPI приложение, реализующее публичный REST/SSE/WebSocket фронт для управления браузерными сессиями и трансляции событий Runner.
- Хранит состояние (сессии, раннеры) в памяти для локальной разработки и unit-тестов.
- Проверяет Keycloak JWT через JWKS и дополнительно выпускает короткоживущие VNC-токены для доступа к прокси.

## Interfaces
- REST:
  - `POST /sessions` — регистрация сессии; автоматически добавляет VNC-токен при наличии VNC-деталей.
  - `GET /sessions` — список активных сессий.
  - `GET /sessions/{id}` — сессия по идентификатору.
  - `POST /sessions/{id}/proxy` — установка/обновление `SessionProxySettings`.
  - `POST /sessions/{id}/touch` — обновление `last_seen_at`.
  - `DELETE /sessions/{id}` — удаление сессии.
  - `POST /sessions/commands` — проксирование упрощённой команды создания в Runner и сохранение ответа.
  - `PATCH /sessions/commands/{id}` — проксирование частичного обновления на Runner с обновлением регистра.
  - `DELETE /sessions/commands/{id}` — удаление сессии через Runner с очисткой локального регистра.
  - `GET /runners` — список зарегистрированных раннеров с признаком здоровья и последним heartbeat.
  - `GET /workstations` — перечень рабочих станций с последними событиями.
  - `GET /workstations/{id}` — конкретная рабочая станция по идентификатору.
  - `POST /workstations` — регистрация/обновление метаданных рабочей станции без события.
  - `POST /workstations/events` — приём `WorkstationEvent` и фиксация последнего состояния/причины.
- Streaming:
  - `GET /events` — SSE-канал, ретранслирующий `SessionEvent` (кеш последнего события на подписчика);
    поддерживает аутентификацию через заголовок `Authorization` или query-параметр
    `access_token` для совместимости с нативным `EventSource`.
  - `WS /events/ws` — WebSocket с тем же потоком событий.
  - `WS /sessions/{id}/ws` — прокси Playwright WebSocket каналов; требует Bearer токен в заголовке или параметре `token`.
  - `POST /events` — приём `SessionEvent` от Runner (HTTP transport) с публикацией через общий bridge; маршрут требует той же
    аутентификации, что и клиентские SSE/REST-вызовы через зависимость `get_current_user`.
- «Внутренние» HTTP/WS запросы могут авторизоваться по источнику IP: CIDR из `GATEWAY_TRUSTED_CIDRS` и (опционально)
  заголовок `GATEWAY_TRUSTED_HEADER` с оригинальным клиентским IP. Совпадение выдаёт синтетического пользователя
  `internal:<ip>` и логирует стратегию `auth_strategy=internal-bypass`.
- Аутентификация: Bearer JWT (Keycloak). Для WebSocket токен передаётся в заголовке `Authorization: Bearer` или параметре `token`.
- Контейнерный образ: `services/gateway/Dockerfile` на базе `python:3.12-slim` ставит прод-зависимости через
  `poetry install --without dev`, монтирует `packages/core` и запускает `uvicorn app.main:create_app`
  (порт 8080). Собирается локально `make gateway-image`, публикуется через `make gateway-image-publish`
  либо GitHub Actions workflow `build-gateway-image` (GHCR `ghcr.io/<owner>/gateway:<tag>` с опциональной подписью Cosign).

## Data & Models
- Переиспользуются модели из `packages/core`: `Session`, `SessionEvent`, `Runner`, `SessionProxySettings`, `SessionVncDetails` и др.
- `Session` теперь хранит прямой `ws_endpoint` от runner'а и проксируемый `ws_public_endpoint`; Gateway больше не перезаписывает
  прямой URL в REST-ответах, чтобы внутренние клиенты могли подключаться без прокси.
- `SessionRegistry`/`RunnerRegistry` — простые in-memory контейнеры с `asyncio.Lock` для потокобезопасности.
- `WorkstationRegistry` — in-memory карта рабочих станций, сохраняет `WorkstationRecord` с последним событием.
- `InMemorySessionEventBridge` (из core) хранит последнее событие и раздаёт подписчикам.
- `WorkstationRecord`/`WorkstationUpsertPayload` — gateway-модели для REST, совместимы с `core.WorkstationMeta`/`WorkstationEvent` и сохраняют идентификаторы/состояние.

## Decisions
- JWKS кэшируется в памяти и повторно запрашивается при отсутствии нужного `kid` (устойчивость к ротации ключей).
- ВNC-токены выдаются как HMAC JWT (`HS256`) через `VncTokenService` с TTL из конфигурации (≤300 сек); секрет читается из `VNC_TOKEN_SECRET` и должен совпадать с `Settings.token_secret` в VNC Gateway.
- Runner-инстансы больше не присылают пред-выданные VNC токены; `VncTokenService.enrich_vnc_details` всегда монтирует подпись, если поле `token` отсутствует, перезаписывая TTL на конфигурационный.
- Enrich-фаза переписывает `http_url`/`websocket_url`, добавляя query `token=<jwt>`, чтобы downstream-клиенты (UI/iframe, tooling) могли пользоваться готовыми ссылками без ручного выставления `X-VNC-Token`.
- Переиспользуем подход из beta-контроллера: для каждого раннера можно настроить шаблоны публичных VNC-URL (HTTP/WS) и при регистрации сессии мы переписываем внутренние адреса на общую точку входа, что позволяет использовать ограниченное число наружных портов.
- SSE реализовано через `StreamingResponse`, WebSocket — нативный FastAPI роутер; для обоих каналов используется единый event bridge.
- WebSocket `/events/ws` теперь прекращает обработку при `AuthenticationError`, чтобы избежать повторного открытия уже закрытого
  соединения; покрыто тестом `test_websocket_event_invalid_token_closes_without_server_error`.
- Маршруты `/workstations` валидируют payload через `WorkstationUpsertPayload`/`WorkstationEvent` и возвращают `WorkstationRecord`, сохраняя идентификаторы и состояние даже при мета-апдейтах.
- Эндпоинты мутаций (`POST /sessions`, `/sessions/{id}/proxy`, `/sessions/{id}/touch`, `DELETE /sessions/{id}`)
  после успешного завершения формируют `SessionEvent` и отправляют его в bridge, чтобы UI обновлялся даже при изменениях,
  инициированных самим Gateway.
- Авторизация завершается до открытия WebSocket, при ошибках соединение закрывается кодом `1008`.
- Реализована внутренняя аутентификация по доверенным сетям: CIDR списки валидируются через `ipaddress`, а WebSocket/HTTP
  зависимости фиксируют стратегию в аудит-логах. Заголовок доверенного IP разбирает список значений (`X-Forwarded-For`).
- Для `WS /sessions/{id}/ws` хранится привязка `session_id`→частный Runner `ws_endpoint` внутри `RunnerRegistry`; наружным клиен
  там выдаётся стабильный публичный путь `/sessions/{id}/ws`, публикуемый теперь как поле `ws_public_endpoint`, а прокси исполь
  зует `websockets` для двунаправленной ретрансляции без изменения прямого URL.
- Командные эндпоинты используют `RunnerCommandClient` (httpx + MockTransport в тестах) и на стороне Gateway трансформируют упрощённый DTO (`browser_name`, `region`, `proxy_id`) в Runner API. При отсутствии `runner_id` выбирается первый доступный раннер из регистра.
- Для предотвращения рассинхронизации контрактов с Runner добавлены unit-тесты, которые валидируют DTO команд Gateway через `SessionCreatePayload`/`SessionUpdatePayload` из Runner и проверяют поддержку алиаса `updated_at` в `core.Session`.
- Health-чек раннеров выполняется через `RunnerHealthClient` (httpx) и сохраняет результат в `RunnerRegistry`. Селектор `select_next` использует круговой обход и фильтрует по признаку здоровья и поддержке VNC, чтобы избежать ручного выбора в роутерах.
- Тесты аутентификатора Keycloak используют `httpx.MockTransport`, чтобы прогонять полный цикл `_fetch_jwks` без прямых правок кэша
  и проверять повторные запросы при смене `kid`, HTTP-ошибки и сбои декодирования JSON.
- Lifespan-хук после discovery обходит только здоровых раннеров, вызывает `GET /sessions` через `RunnerCommandClient.list_sessions` и восстанавливает `SessionRegistry` вместе с веб-сокетными биндингами `RunnerRegistry`. Поток проверен тестом `test_lifespan_restores_sessions_from_healthy_runners`.
- Контейнер формируется на базе `python:3.12-slim`: добавлены системные пакеты (`build-essential`, `python3-dev`, `libffi-dev`),
  чтобы собрать `uvicorn[standard]` зависимости, и Poetry 1.8.3 создает локальное venv. Entry-point использует
  `uvicorn app.main:create_app`, чтобы запускать приложение через фабрику и корректно применять конфигурацию.
  Публикация в GHCR сопровождается опциональной подписью Cosign (переключается флагом `sign_image`).
- Helm chart `docs/helm/platform` описывает деплой Gateway вместе с другими контрол-плейн сервисами, поддерживая передачу
  переменных окружения и Secret-значений (Keycloak, `VNC_TOKEN_SECRET`) через `secretEnv`/`extraEnvFromSecrets`.

## Constraints & Invariants
- `VNC_TOKEN_TTL_SEC` всегда ≤300; нарушение приводит к `ValueError` на старте.
- `VNC_TOKEN_SECRET` обязателен и должен быть согласован с VNC Gateway.
- Локальный `docker-compose` подставляет `VNC_TOKEN_SECRET=dev-secret`, если переменная не задана; в продовых/шареных окружениях
  следует переопределять секрет явно.
- BuildKit cache mounts для Poetry отключены: docker compose выполняет сборку с rootless BuildKit и монтирует кеши с root-владением,
  из-за чего `poetry install --without dev` падал бы с `PermissionError`; вместо этого используем `POETRY_CACHE_DIR=/tmp/pypoetry-cache`
  с правами `1777`.
- `poetry install` выполняется с `--no-root`, потому что исходники (`app/`) копируются после установки зависимостей; убирая флаг, нужно
  перестроить Dockerfile и копировать код до шага установки зависимостей.
- JWT должен содержать `kid` и валидный `exp`; аудит-лог записывает `sub` и `email`/`preferred_username`.
- In-memory хранилища не предназначены для горизонтального масштабирования; восстановление состояния из Runner discovery пока не реализовано.

## Known Gaps / TODO
- [x] Реализовать конфигурируемый обход Keycloak для доверенных внутренних сетей
      (CIDR + опциональный заголовок из `GATEWAY_TRUSTED_HEADER`). Покрыто unit-тестами
      HTTP/SSE/WS (`tests/test_security.py`) и обновлёнными логами `auth_strategy`.
- [x] Реализовать реальные механизмы discovery и синхронизации раннеров/сессий (сейчас только in-memory конфиг). Покрыто
      модулем `app.services.discovery` с поддержкой `static`/`http`, unit-тестами и очисткой веб-сокетных биндингов.
- [x] Вынести секрет для VNC-токенов в конфигурацию и синхронизировать с VNC Gateway. (см. текущий PR)
- [x] Добавить интеграционные тесты с реальной валидацией JWKS (httpx/respx), а не заполнять кэш напрямую. Покрыто unit-тестом
      `test_keycloak_authenticator_fetches_and_caches_jwks`, использующим httpx.MockTransport.
- [x] Обновлять уже сохранённые сессии при изменении шаблонов VNC на раннерах (сейчас применяется только при создании). Выполнено: роутер переобогащает ответы через реестр раннеров, добавлены unit-тесты на обновление шаблонов.
- [x] Реализовать стратегию выбора раннера (учитывать слоты/регион) вместо текущего «первый в списке». Добавлен круговой селектор, отфильтровывающий по здоровью и поддержке VNC.
- [x] Настроить фонового воркера, который периодически опрашивает `/health` у всех раннеров и заполняет реестр. Выполнено через
      lifespan-хук FastAPI (`_runner_maintenance_loop`) с очисткой сессий и health-probe.
- [x] Зафиксирован поток восстановления после рестартов: lifespan делает `GET /sessions`, покрыто тестами `test_list_sessions_returns_*` (runner) и `test_lifespan_restores_sessions_from_healthy_runners` (gateway).

## How to Test
- Локально:
  - `cd services/gateway`
  - `poetry install --no-root`
  - `poetry run pytest -q`
- При необходимости линтинг: `poetry run ruff check .`
- Тест `test_vnc_overrides_apply_runner_templates` проверяет, что VNC-адреса переписываются на публичные шаблоны по аналогии с beta.
- Тесты `test_contract_synchronization.py` гарантируют, что HTTP-команды Gateway совместимы с моделями Runner и `core.Session`.

## Changelog (for agents)
- 2025-10-01 · OpenAI ChatGPT · Реализован FastAPI gateway (REST/SSE/WS), Keycloak JWT, VNC-токены и покрывающие unit-тесты.
- 2025-10-02 · OpenAI ChatGPT · Добавлены публичные VNC-шаблоны для раннеров и переписывание URL при создании сессий по образцу beta-control-plane.
- 2025-10-03 · gpt-5-codex · Вынесен VNC JWT секрет в конфигурацию и синхронизирован с VNC Gateway.
- 2025-10-03 · gpt-5-codex · Добавлен дефолт `VNC_TOKEN_SECRET=dev-secret` для локального docker-compose и задокументирован опциональный override.
- 2025-10-03 · gpt-5-codex · Дополнен `pyproject.toml` обязательным полем authors для корректной работы Poetry package mode.
- 2025-10-03 · gpt-5-codex · Убраны BuildKit cache mounts в Dockerfile, перенесён `POETRY_CACHE_DIR` в `/tmp/pypoetry-cache` (1777) и добавлен `--no-root`, чтобы `docker compose build` не падал при установке зависимостей до копирования исходников.
- 2025-10-03 · gpt-5-codex · Исправлено чтение `GATEWAY_TRUSTED_HEADER` в `GatewaySettings.from_env`: раньше использовался дескриптор класса, что падало при пустом env.
- 2025-10-03 · gpt-5-codex · Задокументирован Helm-чарт control plane (templates + values) с опциями для секретов Gateway.
- 2025-10-05 · gpt-5-codex · Уточнена логика выдачи VNC токенов при пустых значениях от Runner и добавлены покрывающие тесты.
- 2025-10-06 · gpt-5-codex · Разрешена аутентификация SSE через query `access_token`, добавлен unit-тест маршрута `/events`.
- 2025-10-07 · gpt-5-codex · Добавлены командные эндпоинты `/sessions/commands*`, httpx-клиент Runner и покрывающие тесты.
- 2025-10-08 · gpt-5-codex · Реализован HTTP-приёмник `POST /events`, генерация событий на мутациях сессий и тесты доставки в SSE/WS.
- 2025-10-09 · gpt-5-codex · Добавлен HTTP-клиент для health-чеков раннеров, круговой селектор с фильтрами VNC и расширенный `/runners` с данными диагностики.
- 2025-10-10 · gpt-5-codex · Обновление ответов `/sessions` через свежие данные раннеров для пересборки публичных VNC URL и выпуск новых токенов при необходимости; добавлен тест изменения шаблонов.
- 2025-10-11 · gpt-5-codex · Добавлены перекрёстные тесты синхронизации контрактов Gateway↔Runner↔core, чтобы отслеживать регрессии в DTO команд.
- 2025-10-12 · gpt-5-codex · Реализован WebSocket прокси `/sessions/{id}/ws`, хранение приватных `ws_endpoint` в `RunnerRegistry`,
  а также интеграционные тесты на проксирование и обработку ошибок.
- 2025-10-13 · gpt-5-codex · Добавлен сервис discovery (`static`/`http`), фоновые health-пробы с очисткой сессий, новые настройки
  `DISCOVERY_ENDPOINT`/`DISCOVERY_POLL_INTERVAL_SEC` и покрывающие unit-тесты.
- 2025-10-13 · gpt-5-codex · Настроен httpx.MockTransport для тестов JWKS и покрыто кеширование/обработка ошибок
  `KeycloakAuthenticator`.
- 2025-10-14 · gpt-5-codex · Gateway сохраняет прямой `ws_endpoint` и публикует отдельный `ws_public_endpoint`; обновлены роутеры,
  RunnerRegistry и UI/тесты.
- 2025-10-15 · gpt-5-codex · Добавлена конфигурация доверенных CIDR/заголовков, обход аутентификации для внутренних вызовов
  и покрывающие unit-тесты HTTP/SSE/WS.
- 2025-10-16 · gpt-5-codex · Уточнена документация зависимостей безопасности и обработка пустых env-карт для доверенных CIDR.
- 2025-10-17 · gpt-5-codex · Добавлены registry/роуты для рабочих станций, модели `WorkstationRecord`/`WorkstationUpsertPayload` и unit-тесты API контрактов.
- 2025-10-18 · gpt-5-codex · Восстановление сессий при рестарте через `GET /sessions`, расширенный RunnerCommandClient и новые unit-тесты bootstrap.
- 2025-10-19 · gpt-5-codex · Добавлены контейнерный образ Gateway, make-таргеты для сборки/публикации и GitHub Actions пайплайн
  с опциональной подписью Cosign.
- 2025-10-25 · gpt-5-codex · VNC-детали теперь включают подписанный токен прямо в URL, а Gateway и UI потребители используют query `token` fallback вместо ручных заголовков; добавлены покрывающие тесты.
- 2025-10-27 · gpt-5-codex · Уточнены docstring/импорт соглашения в сервисах и тестах, а также обновлены проверки переписывания VNC-URL, чтобы учитывать выдачу токенов в query-параметрах.
- 2025-10-26 · gpt-5-codex · Привёл unit-тесты Gateway к текущей логике VNC-токенов: обновил ожидания URL на парсинг с query `token`, добавил импорт `HttpxMockTransport` и сортировку импортов для совместимости с Ruff.
- 2025-10-28 · gpt-5-codex · Зафиксирована обработка ошибки аутентификации в `/events/ws`, добавлен интеграционный тест на закрытие с кодом 1008 без серверной ошибки.
- 2025-10-30 · gpt-5-codex · Защитил `POST /events` аутентификацией через `get_current_user` и добавил тесты, проверяющие отказ для
  анонимных вызовов и успех для авторизованных клиентов.
- 2025-10-30 · gpt-5-codex · Покрыл обход по доверенным сетям для `POST /events`, чтобы зафиксировать совместимость с внутренними
  раннерами без bearer-токена.
- 2025-10-28 · gpt-5-codex · Обновлён RunnerCommandClient: исключает пустые JSON-тела для GET/DELETE и добавлен регрессионный тест на отсутствие body.
