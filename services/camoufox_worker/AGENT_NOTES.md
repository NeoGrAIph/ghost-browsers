# AGENT_NOTES — camoufox_worker

## Overview
Camoufox worker обеспечивает выполнение короткоживущих браузерных задач в двух режимах: нативный запуск Camoufox внутри контейнера и оркестрация удалённых сессий через Gateway/Runner. Текущий коммит добавляет каркас сервиса, документацию и базовые заглушки для дальнейшей реализации.

## Interfaces
* CLI `python -m worker.main run` для запуска единичной задачи с параметрами URL и таймаутом; выводит JSON с полями результата.
* Планируемые интеграции: очередь задач (Redis/AMQP), HTTP API Gateway/Runner для orchestrator-режима.

## Data & Models
* `worker.jobs.Job` — Pydantic-модель, описывающая параметры задачи (URL, прокси, таймаут). Помимо нормализованного `HttpUrl` хранит исходную строку `url_source`, чтобы браузер открывал URL без навязанного завершающего слэша.
* `worker.jobs.JobStatus`/`JobResult` — структура результата с флагом `ok`, статусом (`success|failure|aborted`), таймстемпами начала/окончания, метриками (`JobMetrics.duration_ms`) и описанием ошибки (`JobError`). Поле `JobMetrics.extra` допускает числовые и строковые значения (например, статусы навигации, тип исключения, длительности).
* `worker.runner_native.run_job` возвращает `JobResult` вместо словаря, применяет per-job proxy и наполняет `JobMetrics.extra` полями `navigation_status`, `navigation_duration_ms`, `timeout_ms`, `exception_type`.

## Decisions
* Выбраны отдельные модули для native и orchestrator режимов, чтобы облегчить параллельную разработку и тестирование.
* В образе подразумевается предварительный `camoufox fetch`; в рантайме операции загрузки запрещены (см. AGENTS.md).
* CLI основан на Click для дальнейшего расширения команды `run` под дополнительные опции.
* При ошибках исполнения Camoufox исключения конвертируются в `JobResult` со статусом `failure`, чтобы потребители могли логировать/ретраить без исключений.

## Constraints & Invariants
* Выполнение под non-root пользователем, без `pip install`/`camoufox fetch` в рантайме.
* Значение `CAMOUFOX_HEADLESS` по умолчанию — `virtual`; ожидается наличие Xvfb в базовом образе Playwright.
* Каждый запуск создаёт изолированный Camoufox context с приоритетом прокси SOCKS > HTTPS > HTTP и закрывает страницу/контекст даже при исключениях. Если Camoufox падает до навигации, `navigation_status` принудительно переводится в `context_failed`.
* Навигация выполняется с таймаутом `job.timeout_sec` (преобразованным в миллисекунды для Camoufox API) и использует исходную строку URL из `Job.url_source`.
* Код должен содержать docstring у каждого публичного объекта (соответствие корневым инструкциям).

## Known Gaps / TODO
- [ ] Реализовать очередь задач и обработку ретраев.
- [ ] Добавить метрики и трейсинг выполнения задач.
- [ ] Реализовать управление профилями/«тумблерами» Camoufox для разных сценариев.

## How to Test
* `poetry install` — установка зависимостей и публикация пакета `worker`.
* `poetry run ruff check .` — статический анализ.
* `poetry run pytest -q` — запуск юнит-тестов (покрытие моделей и нативного раннера через моки).
* `poetry run python -m camoufox path` и `poetry run python -m camoufox version` — валидация окружения Camoufox.

## Changelog (for agents)
* 2024-08-29 · gpt-5-codex · Создан каркас camoufox_worker, добавлены инструкции, документация и тестовые заглушки.
* 2024-08-30 · gpt-5-codex · Обновлён CI workflow: для push-сборок используется fallback-тег с SHA коммита, чтобы избежать пустых Docker tag.
* 2024-08-30 · gpt-5-codex · Исправлен worker build workflow: владелец репозитория приводится к нижнему регистру при формировании GHCR-тега, что устраняет ошибку `repository name must be lowercase`.
* 2024-09-03 · gpt-5-codex · Добавлены структурированные модели результата (`JobResult`, `JobMetrics`, `JobError`), обновлены CLI/runner и покрыты юнит-тестами.
* 2024-09-06 · gpt-5-codex · Реализована поддержка прокси и таймаутов в native-runner, добавлены метрики навигации и регрессионные тесты (proxy/timeout).
* 2025-02-15 · gpt-5-codex · Зафиксирована версия camoufox 0.4.11, добавлены `Job.url_source` и гибкие `JobMetrics.extra`, обновлены статусы навигации, тесты и гайд по запуску.
