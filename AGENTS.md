# AGENTS.md — инструкции для AI-агентов (ghost-browsers, lean)

## Scope & Precedence
Применим ко всему репозиторию. Вложенные `AGENTS.md` (в сервисах/пакетах) имеют приоритет в своих папках.

## Project Map
- `/services/gateway` — FastAPI gateway (REST/SSE/WS API, Keycloak/JWT, VNC токены, discovery).
- `/services/runner` — FastAPI runner (Camoufox lifecycle, warm pool, VNC пайплайн, события).
- `/services/vnc-gateway` — FastAPI proxy для VNC/noVNC/WebSocket с валидацией токенов.
- `/services/camoufox_worker` — Camoufox native worker/CLI и smoke-проверки.
- `/packages/core` — общие Pydantic модели и in-memory event bridge.
- `/apps/ui` — операторская консоль (React + Vite + Zustand), собирается в Nginx образ.
- `/docs` — архитектура, конфигурация, Helm чарты и UI обзор.

## Dev Setup (root)
**Требования:** `pnpm`, `node>=20`, `poetry`, `python>=3.12`.

### Bootstrap
```bash
make bootstrap              # устанавливает pnpm, node, poetry-зависимости и подготавливает git hooks
pnpm install --frozen-lockfile
poetry install --no-root    # внутри конкретного сервиса/пакета
```

### Checks (file-scoped по умолчанию)

* Python (внутри сервиса/пакета):

  ```bash
  poetry run ruff check .
  poetry run pytest -q
  ```
* TypeScript (UI):

  ```bash
  pnpm -C apps/ui lint
  pnpm -C apps/ui test
  ```

### Full check (перед PR)

```bash
make check                  # прогоняет pytest/ruff по Python сервисам и lint/test по UI
```

### Local stack via Docker Compose

* Требуется Docker + BuildKit. Перед первым запуском при необходимости скопируйте `.env.example` → `.env`.
* Команда `docker compose up --build` собирает runner/gateway/vnc-gateway/ui, монтирует warm pool JSON и публикует порты:
  * `8080` — gateway API (`http://localhost:8080`),
  * `8081` — UI (Nginx) c проксированным `/api` → gateway,
  * `8082` — прямой runner для отладки (health/metrics/sessions),
  * `8001` — vnc-gateway для iframe/tokenized URL.
* Переменные с дефолтами заданы в `docker-compose.yml`; секрет `VNC_TOKEN_SECRET` должен совпадать для gateway и vnc-gateway.
* После старта smoke-проверка: `curl http://localhost:8080/health`, `curl http://localhost:8082/health`, `curl http://localhost:8001/metrics`.

## Safety & Permissions

**Можно без подтверждения:** форматирование, file-scoped линт/тест, правки в пределах затронутых модулей, обновление документации/AGENT_NOTES.

**Только после подтверждения:** установка/удаление пакетов (Python/Node), изменения CI/infra, `git push`/force,
массовые перемещения, операции с секретами, генерация миграций.

Секреты не коммитим. Используем `*.env.example` и `docs/configuration.md`.

## PR Gates

`make check` должен быть зелёным. PR-описание: **Summary**, **Testing (команды+вывод)**, **Security**.

## Требования к комментированию кода

1. **Docstring у каждого модуля/класса/функции** (Python) и JSDoc/TSDoc у экспортируемых сущностей (TS):

   * Назначение, входные параметры (имя/тип/семантика), возвращаемое значение, исключения/ошибки.
   * Инварианты и пред-/постусловия; побочные эффекты; потоковая/сетево-I/O специфика.
   * Краткий пример использования.
2. **Inline-комментарии** над нетривиальной логикой: почему выбран подход, альтернативы, что ломается при изменении.
3. **Ссылки** на ADR/внешние спецификации, если решение ними мотивировано.
4. **Запрещены комментарии-шуточки и «мёртвые» TODO**. Все TODO фиксируются в `AGENT_NOTES.md` (см. ниже) с контекстом.

## Файл знаний агента: `AGENT_NOTES.md`

В **каждом сервисе/пакете** должен существовать и поддерживаться файл `AGENT_NOTES.md`, который агент обязан обновлять при каждом значимом изменении. Структура:

```md
# AGENT_NOTES — <module/service name>

## Overview
Краткое назначение модуля, роль в системе.

## Interfaces
Публичные точки (REST/SSE/WS/CLI), форматы, контракты. Ссылки на OpenAPI/AsyncAPI (если есть).

## Data & Models
Ключевые модели/схемы, инварианты, связи.

## Decisions
Принятые решения с обоснованием; ссылки на ADR. Что отвергнуто и почему.

## Constraints & Invariants
Ограничения по производительности, безопасности, окружению.

## Known Gaps / TODO
Список задач (чекбоксами) с контекстом: *что/почему/зачем* и как проверить.

## How to Test
Как запускать юнит/интеграцию/ручные проверки. Готовые команды.

## Changelog (for agents)
Дата · Кем/чем изменено · Коротко *что и почему*.
```

Правила ведения:

* Агент **дополняет** и **не переписывает историю**; для закрытых TODO ставим галочку и ссылку на PR/коммит.
* Каждая нестандартная конструкция в коде должна быть отражена в `AGENT_NOTES.md` (раздел *Decisions* или *Constraints*).

## Camoufox — проверка и правила

* Перед PR и в CI дополнительно выполняй:

```bash
python -m camoufox path
python -m camoufox version
```

* В рантайме контейнера **запрещено** вызывать `python -m camoufox fetch`.
* Headless по умолчанию: `CAMOUFOX_HEADLESS=virtual`.