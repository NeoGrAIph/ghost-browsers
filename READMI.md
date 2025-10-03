# Ghost Browsers Platform

## Обзор
Ghost Browsers — это модульная платформа для управления одноразовыми браузерными сессиями Camoufox. Репозиторий объединяет
несколько сервисов FastAPI, воркеров и React UI, которые совместно обеспечивают выделение сессий, публикацию событий и VNC/
WebSocket доступ операторов. В проекте используется единый набор доменных моделей (`packages/core`) и строгие правила
конфигурации, описанные в `docs/architecture.md` и `docs/configuration.md`.

### Основные задачи платформы
- централизованное управление раннерами, которые запускают Camoufox/Playwright и управляют временем жизни сессий;
- выдача REST/SSE/WebSocket API для внешних клиентов и операторской консоли;
- проксирование VNC, WebSocket и HTTP-трафика к сессиям с применением токенов доступа;
- публикация событий о жизненном цикле сессий и рабочих станций для UI и автоматизации;
- поддержка «тёплого пула» рабочих станций с заранее определёнными fingerprint для ускоренного старта браузеров.

## Структура репозитория
```
apps/ui/                  # SPA консоль оператора (React + Vite)
docs/                     # Архитектура, конфигурация и helm-черты
packages/core/            # Общие модели (Pydantic) и in-memory websocket-бридж
services/gateway/         # Публичный API, авторизация, проксирование ws/sse
services/runner/          # Управление сессиями, warm pool, VNC пайплайны
services/vnc-gateway/     # Публичный noVNC/websockify прокси и валидация токенов
services/camoufox_worker/ # Нативный воркер Camoufox для фоновых задач
```
Дополнительные файлы верхнего уровня: `Makefile`, `pnpm-workspace.yaml`, `smoke.py`, а также `AGENTS.md`/`AGENT_NOTES.md` со
служебными указаниями для агентов-разработчиков.

## Общие доменные модели (`packages/core`)
Пакет `core` содержит Pydantic-модели, которые определяют контракты между всеми сервисами:

- `Runner` и `RunnerState` (`core/models.py`) описывают состояние экземпляров раннера, включая URL API, доступные слоты и
  поддержку VNC. Валидаторы обеспечивают непротиворечивость данных (например, доступные слоты не могут превышать лимит, а
  таймстемпы должны быть timezone-aware).
- `Session`, `SessionStatus`, `SessionEvent` и `SessionEventType` фиксируют полный жизненный цикл сессии, включая idle TTL,
  прямой и публичный WebSocket эндпоинты, метаданные, прокси и VNC-параметры. Валидаторы гарантируют порядок временных
  меток, согласованность рабочих станций и очистку метаданных.
- `SessionProxySettings` и `SessionVncDetails` нормализуют конфигурацию прокси и VNC, выполняют проверки инвариантов и
  подготавливают данные для UI.
- `WorkstationMeta`, `WorkstationEvent`/`WorkstationEventType` и `WorkstationState` описывают пул рабочих станций, который
  используется warm pool'ом.
- `InMemorySessionEventBridge` (`core/websocket_bridge.py`) реализует in-memory fan-out из очередей `asyncio` и обеспечивает
  повторную отправку последнего события (`replay_latest`) при переподключениях клиентов.

Этот пакет импортируется из сервисов runner/gateway/vnc-gateway, а также из UI (через API) для строгой типизации обмена.

## Runner Service (`services/runner/app`)
### FastAPI приложение и маршруты
- `main.py` поднимает приложение FastAPI, настраивает логирование и экспортирует маршруты:
  - `/health` собирает метрики сессий и теплого пула, нормализует базовые URL (функция `_normalise_base_url`) и возвращает
    структуру, которую опрашивают gateway и smoke-тесты;
  - CRUD-эндпоинты для `/sessions` используют `SessionManager` и возвращают/обновляют модели из `core`. При нехватке
    ресурсов генерируется `SessionCapacityError` → HTTP 429;
  - `/metrics` публикует Prometheus метрики через `prometheus_client`;
  - хук `startup`/`shutdown` запускает и останавливает фонового «reaper».
- Роутер `routers/workstations.py` предоставляет REST API для управления warm pool'ом: листинг, резервирование, пометку busy,
  отмену, release, restart, drain и enable. Здесь же выполняется трансляция `WarmPoolStateError` в HTTP ошибки.

### Конфигурация и зависимости
- `config/settings.py` описывает `RunnerSettings` с полным набором env-переменных (runner_id, camoufox_path, лимиты слотов,
  warm pool, VNC и прокси). Валидаторы проверяют диапазоны портов и дисплеев; метод `from_env` считывает переменные с
  приведением типов.
- `config/warm_pool.py` парсит JSON-конфигурацию пула (`WarmPoolConfig`, `WorkstationConfigEntry`) и обеспечивает уникальность
  идентификаторов. Ошибки оборачиваются в `WarmPoolConfigError`.
- `dependencies/session_manager.py` собирает singleton-зависимости с помощью `lru_cache`: настройки, паблишеры событий,
  `ProcessVncController`, `WarmPoolManager`.

### Управление сессиями
- `session_manager.py` реализует `SessionManager`: хранение `Session` в памяти, публикация событий (`SessionEventPublisher`),
  подсчёт активных сессий и запуск idle reaper'а. Основные операции:
  - `create_session` резервирует VNC (через `_resolve_vnc`), получает браузер (через `_acquire_browser_handle`, который
    выбирает тёплый слот или делает cold launch), создаёт `Session` и публикует `SessionEventType.CREATED`;
  - `update_session` и `end_session` обновляют модель, пересчитывают активные сессии, закрывают браузеры/VNC и освобождают
    тёплые рабочие станции при переходе в `DEAD`;
  - `reap_expired_sessions` вычисляет истекшие по idle TTL сессии и завершает их с `reason="idle-timeout"`;
  - вспомогательные методы обрабатывают warm pool (`_reserve_warm_slot`, `_mark_warm_slot_busy`, `_release_warm_slot`),
    управление браузерными процессами (`_launch_cold_browser`, `_shutdown_browser`), VNC-хендлами и метриками.
- В `browser.py` определяется `launch_browser`, который запускает `playwright launch-server` с учётом `CAMOUFOX_BINARY` и
  читает `wsEndpoint`; `BrowserSessionHandle.shutdown` корректно завершает процесс.
- `events.py` предоставляет in-memory и HTTP паблишеры для сессий и рабочих станций (SSE/WebSocket адаптеры, callback-
  обёртки, HTTP транспорт для отправки событий в gateway).
- `vnc.py` управляет пайплайном Xvfb → x11vnc → websockify: распределяет дисплеи и порты, валидирует наличие бинарей и
  возвращает `SessionVncDetails` с публичными URL и токенами.
- `warm_pool.py` реализует конечный автомат `WarmPoolState`, запуск Camoufox в тёплых слотах, перезапуски, дренаж, сбор метрик
  и публикацию событий `WorkstationEvent`.
- `metrics.py` регистрирует Prometheus-метрики (счётчики reaper'а, VNC, warm pool, latency и т. д.).
- `logging.py` настраивает формат логов с обязательными полями `session_id`, `workstation_id`, `fingerprint_id`.

## Gateway Service (`services/gateway/app`)
Сервис FastAPI, который:
- реализует REST/SSE/WebSocket API для управления сессиями и проксирования событий (см. роуты `routers/sessions.py`,
  `routers/events.py`, `routers/runners.py`, `routers/workstations.py`);
- проверяет Keycloak JWT и внутренние токены (`security/keycloak.py`, `security/vnc.py`);
- хранит in-memory реестр раннеров (`services/runner_registry.py`, `services/runner_health.py`), отображение сессий и
  рабочих станций (`session_registry.py`, `workstation_registry.py`), а также клиента для обращения к runner'ам
  (`runner_client.py`) и discovery-механизм для internal DNS/Kubernetes (`services/discovery.py`);
- предоставляет WebSocket прокси к раннерам (`services/runner_ws_proxy.py`) и модуль переопределения VNC (`services/vnc_overrides.py`).

## VNC Gateway (`services/vnc-gateway/app`)
Независимый FastAPI сервис `camou_vnc_gateway`:
- читает конфигурацию (`config.py`), инициализирует метрики и зависимости (`dependencies.py`);
- верифицирует короткоживущие VNC-токены (`token.py`) и проксирует трафик к websockify через `proxy.py` и `routes.py`;
- предоставляет health и metrics эндпоинты для мониторинга.

## Camoufox Worker (`services/camoufox_worker`)
Пакет Python с CLI/воркерами для фоновых задач Camoufox:
- `worker/` содержит реализации задач (health-check, warmup и т. п.),
- `bin/` — точку входа командной утилиты,
- `smoke.py` — быстрые проверки окружения.

## UI (`apps/ui`)
Одностраничное приложение на React + Vite:
- авторизация через Keycloak, отображение списка сессий и теплых рабочих станций,
- интеграция с REST/SSE/WebSocket API gateway,
- сборка и проверки выполняются через `pnpm lint` / `pnpm test`.

## Документация
- `docs/architecture.md` описывает архитектуру (зоны доверия, контракты, SLA).
- `docs/configuration.md` содержит переменные окружения, схемы helm-развёртывания и чек-листы безопасности.

## Сборка и запуск
### Bootstrap окружения
```bash
```
Зависимости: `pnpm`, `node >= 20`, `poetry`, `python >= 3.12`.

### Локальные проверки по сервисам
```bash
```

### Комплексная проверка
```bash
```

## Потоки данных и взаимодействия
1. Клиент (UI или внешний сервис) вызывает `POST /sessions` на gateway.
2. Gateway выбирает runner через `RunnerRegistry`, перенаправляет запрос `SessionCreatePayload` и регистрирует сессию в
   своём `SessionRegistry`.
3. Runner через `SessionManager` резервирует теплую рабочую станцию (если доступно) или запускает новый процесс Playwright.
4. При успешном создании runner публикует `SessionEvent` в in-memory bridge и отправляет payload обратно.
5. Gateway ретранслирует события через SSE/WebSocket, обновляет реестр, выдает публичный WebSocket (`/sessions/{id}/ws`) и
   при необходимости токенизированный VNC endpoint через VNC gateway.
6. VNC gateway валидирует токен, подключается к websockify и отдаёт UI поток кадров.
7. Idle reaper runner'а завершает просроченные сессии и выпускает warm pool слоты; gateway отражает изменения в UI.

## Дополнительные материалы
- `AGENT_NOTES.md` в каждом пакете/сервисе описывает инварианты, TODO и историю изменений.
- `smoke.py` и тестовые директории содержат примеры использования API и сценарии для регрессионного тестирования.