# AGENT_NOTES — core

## Overview
`camou-core` предоставляет единый контракт между Runner, Gateway, VNC Gateway и UI.
Содержит Pydantic-модели для раннеров и сессий, а также утилиты для ретрансляции
событий, чтобы сервисы и фронтенд разделяли одну схему данных.

## Interfaces
- Python API (`core.__all__`): `Runner`, `Session`, `SessionEvent`, перечисления
  состояний, настройки прокси/VNC, `AbstractSessionEventBridge`,
  `InMemorySessionEventBridge`.
- Событийный мост: абстрактные методы `publish(event)` и `subscribe()` возвращают
  асинхронный итератор событий, повторяя будущий контракт Gateway ↔ UI.
- Поддерживается опция `subscribe(replay_latest=True)` для мгновенного
  получения последнего события при реконнекте клиента.

## Data & Models
- `Runner`: идентификатор, `base_url`, состояние, слоты, флаг `healthy`, поддержка
  VNC (`supports_vnc`), время последнего heartbeat, capability-флаги. Идентификаторы
  триммируются и не допускают пустых значений.
- `Session`: UUID, `runner_id`, статус (`INIT→DEAD`), `created_at`, `last_seen_at`
  (alias `updated_at`), опциональный `ended_at`, флаги `headless`, `idle_ttl_seconds`
  (30–3600), `browser`, `labels`, `start_url`, `start_url_wait`, `ws_endpoint`,
  `ws_public_endpoint`, `vnc_enabled`, `proxy`, `vnc`, произвольная метадата, а также
  `workstation_id`, `workstation_fingerprint_id` и вложенный `workstation` с
  публичными метаданными. Модель гарантирует согласованность top-level полей с
  вложенным объектом.
- `SessionEvent`: уникальный `id`, тип (`created|updated|ended`), snapshot сессии,
  время возникновения, опциональная причина, удобный флаг `is_terminal` (TRUE только
  для `SessionStatus.DEAD`).
- `WorkstationMeta`: `id`, `fingerprint_id`, `state`, опциональный `proxy_summary`,
  пользовательская метадата (фильтрована под UI).
- `WorkstationEvent`: уникальный `id`, `type` (`created|updated|released`), snapshot
  метаданных, `occurred_at`, опциональная `reason` (строго trim/не пустая).
- Подмодели: `SessionProxySettings` (минимум один URL), `SessionVncDetails`
  (хотя бы один из HTTP/WS URL, опциональный токен с TTL ≤ 300 секунд).
- Перечисления: `SessionStatus`, `StartUrlWait`, `SessionEventType`,
  `WorkstationState`, `WorkstationEventType`.

## Decisions
- Используем `frozen=True` для моделей, чтобы сделать объекты неизменяемыми и
  безопасными для кешей/переиспользования.
- TTL токена ограничен 300 сек в соответствии с `docs/configuration.md`.
- В `InMemorySessionEventBridge` каждый подписчик получает собственную очередь —
  гарантирует отсутствие влияния подписчиков друг на друга.
- Отказались от внешнего брокера событий: единый in-memory мост на `asyncio`
  считается продукционным решением, чтобы упрощать развёртывания без Redis/Kafka.
- Все валидаторы снабжены подробными docstring’ами с аргументами и примерами,
  чтобы соблюсти корневые требования к документации.
- Pytest-конфигурация добавляет core-пакет в `sys.path` через `tests/conftest.py`
  и использует только `--strict-markers`/`--maxfail=1`; тесты требуют фактической
  установки зависимостей (`pydantic`, `httpx` и пр.), т.к. защитные пропуски
  удалены. Покрытие запускается вручную при наличии плагина.

## Constraints & Invariants
- Все временные метки должны быть timezone-aware (`tzinfo` не `None`).
- `Session.last_seen_at ≥ created_at`; если задано, `ended_at ≥ created_at`.
- `idle_ttl_seconds` в диапазоне 30–3600 секунд.
- `Runner.available_slots ≤ total_slots`; OFFLINE-раннер не может быть `healthy`.
- `SessionProxySettings` требует хотя бы одного URL, предотвращая пустые прокси.
- `SessionVncDetails` требует хотя бы один из HTTP/WS URL и валидный TTL при наличии токена.
- `Session.workstation` валидируется на совпадение с `workstation_id` и
  `workstation_fingerprint_id`, чтобы избежать рассинхронизации payload’ов.
- `WorkstationEvent` требует `occurred_at` с tzinfo и непустую `reason` при наличии.

## Known Gaps / TODO
- [ ] Провести нагрузочное тестирование in-memory моста под массовыми подписками,
      когда появятся целевые SLO по задержкам от команды эксплуатации.

## How to Test
- Установить зависимости: `poetry install --no-root` (в каталоге `packages/core`).
- Линтер: `poetry run ruff check .`
- Тесты: `poetry run pytest -q`
  - Дополнительно: `poetry run pytest --cov=core --cov-report=term-missing`, если
    установлен `pytest-cov`.

## Changelog (for agents)
- 2025-10-07 · gpt-5-codex — Зафиксировано решение использовать in-memory мост
  как продукционный, обновлены Known Gaps.
- 2025-02-14 · ChatGPT — Уточнены docstring’и валидаторов, добавлен модульный
  docstring для тестов; функциональное поведение не изменено.
- 2025-10-02 · ChatGPT — Согласованы поля с beta-веткой: статусы `INIT→DEAD`, `StartUrlWait`,
  расширенные `SessionVncDetails`, флаг `supports_vnc`, TTL `idle_ttl_seconds`, обновлены тесты.
- 2025-10-01 · ChatGPT — Добавлена поддержка replay_latest для моста, усилены валидаторы идентификаторов, добавлен флаг is_terminal.
- 2024-08-30 · ChatGPT — Описаны модели Runner/Session/Event, реализован in-memory
  мост событий, обновлены инструкции и тесты.
- 2025-02-21 · ChatGPT — Добавлены регрессионные тесты валидации моделей (Runner/SessionEvent/VNC/Proxy) и pytest-конфигурация с покрытием.
- 2025-02-23 · gpt-5-codex — Удалены `pytest.importorskip`; тесты требуют установки зависимостей,
  добавлена документация по запуску без пропусков.
- 2025-10-14 · gpt-5-codex — Расширен `Session` полем `ws_public_endpoint` и обновлены тесты сериализации.
- 2025-10-15 · ChatGPT — Добавлены модели и события рабочей станции, расширен контракт `Session`
  workstation-полями, обновлены тесты сериализации/валидации.
