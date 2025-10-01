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
- Streaming:
  - `GET /events` — SSE-канал, ретранслирующий `SessionEvent` (кеш последнего события на подписчика);
    поддерживает аутентификацию через заголовок `Authorization` или query-параметр
    `access_token` для совместимости с нативным `EventSource`.
  - `WS /events/ws` — WebSocket с тем же потоком событий.
  - `WS /sessions/{id}/ws` — прокси Playwright WebSocket каналов; требует Bearer токен в заголовке или параметре `token`.
  - `POST /events` — приём `SessionEvent` от Runner (HTTP transport) с публикацией через общий bridge.
- Аутентификация: Bearer JWT (Keycloak). Для WebSocket токен передаётся в заголовке `Authorization: Bearer` или параметре `token`.

## Data & Models
- Переиспользуются модели из `packages/core`: `Session`, `SessionEvent`, `Runner`, `SessionProxySettings`, `SessionVncDetails` и др.
- `SessionRegistry`/`RunnerRegistry` — простые in-memory контейнеры с `asyncio.Lock` для потокобезопасности.
- `InMemorySessionEventBridge` (из core) хранит последнее событие и раздаёт подписчикам.

## Decisions
- JWKS кэшируется в памяти и повторно запрашивается при отсутствии нужного `kid` (устойчивость к ротации ключей).
- ВNC-токены выдаются как HMAC JWT (`HS256`) через `VncTokenService` с TTL из конфигурации (≤300 сек); секрет читается из `VNC_TOKEN_SECRET` и должен совпадать с `Settings.token_secret` в VNC Gateway.
- Runner-инстансы больше не присылают пред-выданные VNC токены; `VncTokenService.enrich_vnc_details` всегда монтирует подпись, если поле `token` отсутствует, перезаписывая TTL на конфигурационный.
- Переиспользуем подход из beta-контроллера: для каждого раннера можно настроить шаблоны публичных VNC-URL (HTTP/WS) и при регистрации сессии мы переписываем внутренние адреса на общую точку входа, что позволяет использовать ограниченное число наружных портов.
- SSE реализовано через `StreamingResponse`, WebSocket — нативный FastAPI роутер; для обоих каналов используется единый event bridge.
- Эндпоинты мутаций (`POST /sessions`, `/sessions/{id}/proxy`, `/sessions/{id}/touch`, `DELETE /sessions/{id}`)
  после успешного завершения формируют `SessionEvent` и отправляют его в bridge, чтобы UI обновлялся даже при изменениях,
  инициированных самим Gateway.
- Авторизация завершается до открытия WebSocket, при ошибках соединение закрывается кодом `1008`.
- Для `WS /sessions/{id}/ws` хранится привязка `session_id`→частный Runner `ws_endpoint` внутри `RunnerRegistry`; наружным клиентам
  выдаётся стабильный публичный путь `/sessions/{id}/ws`, а прокси использует `websockets` для двунаправленной ретрансляции.
- Командные эндпоинты используют `RunnerCommandClient` (httpx + MockTransport в тестах) и на стороне Gateway трансформируют упрощённый DTO (`browser_name`, `region`, `proxy_id`) в Runner API. При отсутствии `runner_id` выбирается первый доступный раннер из регистра.
- Для предотвращения рассинхронизации контрактов с Runner добавлены unit-тесты, которые валидируют DTO команд Gateway через `SessionCreatePayload`/`SessionUpdatePayload` из Runner и проверяют поддержку алиаса `updated_at` в `core.Session`.
- Health-чек раннеров выполняется через `RunnerHealthClient` (httpx) и сохраняет результат в `RunnerRegistry`. Селектор `select_next` использует круговой обход и фильтрует по признаку здоровья и поддержке VNC, чтобы избежать ручного выбора в роутерах.

## Constraints & Invariants
- `VNC_TOKEN_TTL_SEC` всегда ≤300; нарушение приводит к `ValueError` на старте.
- `VNC_TOKEN_SECRET` обязателен и должен быть согласован с VNC Gateway.
- JWT должен содержать `kid` и валидный `exp`; аудит-лог записывает `sub` и `email`/`preferred_username`.
- In-memory хранилища не предназначены для горизонтального масштабирования; восстановление состояния из Runner discovery пока не реализовано.

## Known Gaps / TODO
- [ ] Реализовать реальные механизмы discovery и синхронизации раннеров/сессий (сейчас только in-memory конфиг).
- [x] Вынести секрет для VNC-токенов в конфигурацию и синхронизировать с VNC Gateway. (см. текущий PR)
- [ ] Добавить интеграционные тесты с реальной валидацией JWKS (httpx/respx), а не заполнять кэш напрямую.
- [x] Обновлять уже сохранённые сессии при изменении шаблонов VNC на раннерах (сейчас применяется только при создании). Выполнено: роутер переобогащает ответы через реестр раннеров, добавлены unit-тесты на обновление шаблонов.
- [x] Реализовать стратегию выбора раннера (учитывать слоты/регион) вместо текущего «первый в списке». Добавлен круговой селектор, отфильтровывающий по здоровью и поддержке VNC.
- [ ] Настроить фонового воркера, который периодически опрашивает `/health` у всех раннеров и заполняет реестр.

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
- 2025-10-05 · gpt-5-codex · Уточнена логика выдачи VNC токенов при пустых значениях от Runner и добавлены покрывающие тесты.
- 2025-10-06 · gpt-5-codex · Разрешена аутентификация SSE через query `access_token`, добавлен unit-тест маршрута `/events`.
- 2025-10-07 · gpt-5-codex · Добавлены командные эндпоинты `/sessions/commands*`, httpx-клиент Runner и покрывающие тесты.
- 2025-10-08 · gpt-5-codex · Реализован HTTP-приёмник `POST /events`, генерация событий на мутациях сессий и тесты доставки в SSE/WS.
- 2025-10-09 · gpt-5-codex · Добавлен HTTP-клиент для health-чеков раннеров, круговой селектор с фильтрами VNC и расширенный `/runners` с данными диагностики.
- 2025-10-10 · gpt-5-codex · Обновление ответов `/sessions` через свежие данные раннеров для пересборки публичных VNC URL и выпуск новых токенов при необходимости; добавлен тест изменения шаблонов.
- 2025-10-11 · gpt-5-codex · Добавлены перекрёстные тесты синхронизации контрактов Gateway↔Runner↔core, чтобы отслеживать регрессии в DTO команд.
- 2025-10-12 · gpt-5-codex · Реализован WebSocket прокси `/sessions/{id}/ws`, хранение приватных `ws_endpoint` в `RunnerRegistry`,
  а также интеграционные тесты на проксирование и обработку ошибок.
