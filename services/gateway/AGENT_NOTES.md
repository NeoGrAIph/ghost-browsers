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
  - `GET /runners` — список зарегистрированных раннеров.
- Streaming:
  - `GET /events` — SSE-канал, ретранслирующий `SessionEvent` (кеш последнего события на подписчика).
  - `WS /events/ws` — WebSocket с тем же потоком событий.
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
- Авторизация завершается до открытия WebSocket, при ошибках соединение закрывается кодом `1008`.

## Constraints & Invariants
- `VNC_TOKEN_TTL_SEC` всегда ≤300; нарушение приводит к `ValueError` на старте.
- `VNC_TOKEN_SECRET` обязателен и должен быть согласован с VNC Gateway.
- JWT должен содержать `kid` и валидный `exp`; аудит-лог записывает `sub` и `email`/`preferred_username`.
- In-memory хранилища не предназначены для горизонтального масштабирования; восстановление состояния из Runner discovery пока не реализовано.

## Known Gaps / TODO
- [ ] Реализовать реальные механизмы discovery и синхронизации раннеров/сессий (сейчас только in-memory конфиг).
- [x] Вынести секрет для VNC-токенов в конфигурацию и синхронизировать с VNC Gateway. (см. текущий PR)
- [ ] Добавить интеграционные тесты с реальной валидацией JWKS (httpx/respx), а не заполнять кэш напрямую.
- [ ] Обновлять уже сохранённые сессии при изменении шаблонов VNC на раннерах (сейчас применяется только при создании).

## How to Test
- Локально:
  - `cd services/gateway`
  - `poetry install --no-root`
  - `poetry run pytest -q`
- При необходимости линтинг: `poetry run ruff check .`
- Тест `test_vnc_overrides_apply_runner_templates` проверяет, что VNC-адреса переписываются на публичные шаблоны по аналогии с beta.

## Changelog (for agents)
- 2025-10-01 · OpenAI ChatGPT · Реализован FastAPI gateway (REST/SSE/WS), Keycloak JWT, VNC-токены и покрывающие unit-тесты.
- 2025-10-02 · OpenAI ChatGPT · Добавлены публичные VNC-шаблоны для раннеров и переписывание URL при создании сессий по образцу beta-control-plane.
- 2025-10-03 · gpt-5-codex · Вынесен VNC JWT секрет в конфигурацию и синхронизирован с VNC Gateway.
- 2025-10-05 · gpt-5-codex · Уточнена логика выдачи VNC токенов при пустых значениях от Runner и добавлены покрывающие тесты.
