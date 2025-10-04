# AGENTS.md — camoufox_worker (Camoufox native)

## Commands
```bash
poetry install --no-root                 # prod зависимости для worker CLI
poetry run ruff check .
poetry run pytest -q                     # unit тесты задач и smoke-утилит
python -m camoufox path && python -m camoufox version
```

## Modes & env

* `WORKER_MODE=native|orchestrator` (default: `native`) переключает основной entrypoint в `worker/__main__.py`.
* `GATEWAY_URL`, `GATEWAY_TOKEN`, `RUNNER_URL` используются задачами для обращения к control-plane. В docker compose worker не запускается автоматически, но smoke-скрипты предполагают `gateway` по адресу `http://gateway:8080`.

## Camoufox

* Браузер предзагружается при сборке образа (`services/camoufox_worker/Dockerfile`). В рантайме `python -m camoufox fetch` запрещён.
* `CAMOUFOX_HEADLESS=virtual` по умолчанию; отдельные задачи могут переопределять флаг через переменные окружения.
* Диагностика: `python -m camoufox path`/`version`; smoke задача `worker/smoke.py` проверяет доступность бинаря и версию.

## Don’t

* Не менять пользователя контейнера; не выполнять `pip install`/`fetch` на проде.
* Не хранить секреты/прокси в репозитории — используйте `.env`/Kubernetes Secret.

