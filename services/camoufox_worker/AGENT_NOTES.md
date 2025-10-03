# AGENT_NOTES — camoufox_worker

## Overview
Camoufox worker обеспечивает выполнение короткоживущих браузерных задач в двух режимах: нативный запуск Camoufox внутри контейнера и оркестрация удалённых сессий через Gateway/Runner. Реализованы асинхронные HTTP-хелперы для orchestrator-режима с ретраями, единый CLI, юнит-тесты и полноценный FastAPI-сервис для проксирования runner'а (REST + WebSocket) c поддержкой VNC.

## Interfaces
* CLI `python -m worker.main run` для запуска единичной задачи с параметрами URL и таймаутом; выводит JSON с полями результата. Режим выбирается через `--mode` или `WORKER_MODE`, для orchestrator доступны опции/ENV `--gateway-url` (`GATEWAY_URL`), `--gateway-token` (`GATEWAY_TOKEN`), `--poll-timeout`, `--poll-interval`.
* Контейнерный entrypoint `bin/worker-launch.sh` отображает переменные `WORKER_*` (URL, таймауты, режим, gateway) в CLI и при явной передаче аргументов делегирует управление `python -m worker.main ...`.
* FastAPI сервис (`worker.service.create_app`) предоставляет REST API `GET/POST /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/touch`, `DELETE /sessions/{id}`, `GET /health`, `GET /metrics`, а также WebSocket `/sessions/{id}/ws` для проксирования Playwright-трафика. Прокси вебсокета повторно использует runner endpoint и поддерживает двунаправленную пересылку.
  Ответы теперь содержат одновременно прямой `ws_endpoint` от runner'а и `ws_proxy_endpoint` с путём прокси `/sessions/{id}/ws`, чтобы клиенты могли выбирать прямое соединение при доступности.

## Data & Models
* `worker.jobs.Job` — Pydantic-модель, описывающая параметры задачи (URL, прокси, таймаут). Помимо нормализованного `HttpUrl` хранит исходную строку `url_source`, чтобы браузер открывал URL без навязанного завершающего слэша.
* `worker.jobs.JobStatus`/`JobResult` — структура результата с флагом `ok`, статусом (`success|failure|aborted`), таймстемпами начала/окончания, метриками (`JobMetrics.duration_ms`) и описанием ошибки (`JobError`). Поле `JobMetrics.extra` допускает числовые и строковые значения (например, статусы навигации, тип исключения, длительности).
* `worker.runner_native.run_job` возвращает `JobResult` вместо словаря, применяет per-job proxy и наполняет `JobMetrics.extra` полями `navigation_status`, `navigation_duration_ms`, `timeout_ms`, `exception_type`.
* `worker.runner_orch.run_orchestrated_job` использует те же модели `Job`/`JobResult`, создаёт сессию через Gateway, обновляет прокси/heartbeat, собирает метаданные (`session_id`, `poll_attempts`, `session_status`, `touched_at`) и конвертирует ошибки/таймауты в `JobError`.

## Decisions
* Выбраны отдельные модули для native и orchestrator режимов, чтобы облегчить параллельную разработку и тестирование.
* В образе подразумевается предварительный `camoufox fetch`; в рантайме операции загрузки запрещены (см. AGENTS.md).
* CLI основан на Click для дальнейшего расширения команды `run` под дополнительные опции.
* При ошибках исполнения Camoufox исключения конвертируются в `JobResult` со статусом `failure`, чтобы потребители могли логировать/ретраить без исключений.
* Orchestrator-helpers используют `httpx.AsyncClient` с Bearer-аутентификацией, экспоненциальным бэкоффом (5xx/сетевые ошибки) и гарантированным `DELETE` в блоке `finally`.
* FastAPI-слой повторно использует runner REST API, нормализует wsEndpoint и обеспечивает гибкую конфигурацию обязательных флагов браузера через `WorkerSettings.browser_required_flags`, объединяя их с опциональными флагами из запроса без правок кода при изменении набора ключей.
* Pytest-конфигурация добавляет каталог `services/camoufox_worker` в `sys.path`,
  регистрирует маркер `anyio` и оставляет только `--strict-markers`/`--maxfail=1`
  для базового запуска без `pytest-cov`. Поскольку защитные пропуски удалены,
  тесты требуют установки зависимостей (`pydantic`, `httpx`, `camoufox`).
  Авто-fixture `reset_worker_environment` продолжает сбрасывать `WORKER_MODE`,
  прокси и креды Gateway между тестами, а `conftest.py` подменяет модуль
  `camoufox` лёгкой заглушкой до monkeypatch'ей тестов.
* Dockerfile устанавливает зависимости через Poetry (`poetry.lock`), копирует `worker/` и `bin/worker-launch.sh` под пользователем `pwuser` и допускает переопределение версии `camoufox` build-аргументом.
* `worker.queue` реализует консьюмера задач с поддержкой Redis Streams, AMQP и in-memory backend, ретраями/идемпотентностью, Prometheus-метриками и структурированными JSON-логами. Исполнители инжектируются, что позволяет переопределять стратегию запуска задач.
* Helm chart `docs/helm/platform` разворачивает worker рядом с Gateway/Runner, позволяет объявлять секреты (`GATEWAY_TOKEN`, proxy creds) через `secretEnv` и пример `camoufox-worker.values.yaml`.

## Constraints & Invariants
* Выполнение под non-root пользователем, без `pip install`/`camoufox fetch` в рантайме.
* Значение `CAMOUFOX_HEADLESS` по умолчанию — `virtual`; ожидается наличие Xvfb в базовом образе Playwright.
* Каждый запуск создаёт изолированный Camoufox context с приоритетом прокси SOCKS > HTTPS > HTTP и закрывает страницу/контекст даже при исключениях. Если Camoufox падает до навигации, `navigation_status` принудительно переводится в `context_failed`.
* Навигация выполняется с таймаутом `job.timeout_sec` (преобразованным в миллисекунды для Camoufox API) и использует исходную строку URL из `Job.url_source`.
* Для orchestrator-режима обязательны `GATEWAY_URL` и `GATEWAY_TOKEN`; при удалении сессии 404 считается идемпотентным успехом.
* Код должен содержать docstring у каждого публичного объекта (соответствие корневым инструкциям).

## Known Gaps / TODO
- [x] Реализовать очередь задач и обработку ретраев. (см. `worker.queue.JobQueueConsumer`)
- [x] Добавить метрики и трейсинг выполнения задач. (Prometheus счётчики/гистограммы + структурированные JSON-логи)
- [x] Реализовать управление профилями/«тумблерами» Camoufox для разных сценариев. (`WORKER_PROFILE_TOGGLES`, `JobQueueMessage.profile_toggles`)

## How to Test
* `poetry install` — установка зависимостей и публикация пакета `worker`.
* `poetry run ruff check .` — статический анализ.
* `poetry run pytest -q` — юнит-тесты (модели задач, CLI, нативный раннер с Camoufox-моками и orchestrator-хелперы через `httpx.MockTransport`).
  - Дополнительно: `poetry run pytest --cov=worker --cov-report=term-missing`, если установлен `pytest-cov`.
* `poetry run python -m camoufox path` и `poetry run python -m camoufox version` — валидация окружения Camoufox.
* `docker run --rm ghcr.io/<org>/camoufox-worker:latest -- --help` — smoke-проверка entrypoint `worker-launch.sh`.

## Changelog (for agents)
* 2024-08-29 · gpt-5-codex · Создан каркас camoufox_worker, добавлены инструкции, документация и тестовые заглушки.
* 2024-08-30 · gpt-5-codex · Обновлён CI workflow: для push-сборок используется fallback-тег с SHA коммита, чтобы избежать пустых Docker tag.
* 2024-08-30 · gpt-5-codex · Исправлен worker build workflow: владелец репозитория приводится к нижнему регистру при формировании GHCR-тега, что устраняет ошибку `repository name must be lowercase`.
* 2024-09-03 · gpt-5-codex · Добавлены структурированные модели результата (`JobResult`, `JobMetrics`, `JobError`), обновлены CLI/runner и покрыты юнит-тестами.
* 2024-09-06 · gpt-5-codex · Реализована поддержка прокси и таймаутов в native-runner, добавлены метрики навигации и регрессионные тесты (proxy/timeout).
* 2025-02-15 · gpt-5-codex · Зафиксирована версия camoufox 0.4.11, добавлены `Job.url_source` и гибкие `JobMetrics.extra`, обновлены статусы навигации, тесты и гайд по запуску.
* 2025-02-17 · gpt-5-codex · Реализованы async-хелперы orchestrator-режима (create/touch/proxy/delete/poll) с ретраями, обновлён CLI (ENV + gateway credentials) и добавлены pytest-моки `httpx.MockTransport` для проверки ретраев/ошибок.
* 2025-02-20 · gpt-5-codex · Добавлен `poetry.lock`, переработан Dockerfile (Poetry-install под `pwuser`, entrypoint `worker-launch.sh`, build-arg camoufox) и описан контейнерный запуск.
* 2025-02-21 · ChatGPT · Расширены юнит-тесты (CLI, Camoufox мок, orchestrator HTTP flow), добавлен автofixture для очистки ENV и pytest-конфигурация с покрытием.
* 2025-02-23 · gpt-5-codex · Удалены `pytest.importorskip`, глобально прокинут shim `camoufox`,
  обновлены инструкции по зависимостям и тестам.
* 2025-02-24 · ChatGPT · Добавлен модуль очереди с Redis/AMQP адаптерами, Prometheus метриками, тумблерами профиля и тестами интеграций.
* 2025-02-26 · ChatGPT · Интегрирован FastAPI worker (REST/VNC/WebSocket), добавлены конфиги `worker.config`, обязательные флаги браузера и unit-тесты `test_service.py`; обновлены зависимости Poetry.
* 2025-10-03 · gpt-5-codex · Добавлены Helm-шаблоны/values для camoufox-worker с примерами секретов и описанием деплоя.
* 2025-10-14 · gpt-5-codex · Возврат прямого runner `ws_endpoint` в REST-ответах и добавление поля `ws_proxy_endpoint` вместо перезаписи URL прокси.
