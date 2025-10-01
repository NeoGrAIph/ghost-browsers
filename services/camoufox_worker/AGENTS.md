# AGENTS.md — camoufox_worker (Camoufox native)

## Commands
```bash
poetry install --no-root
poetry run ruff check .
poetry run pytest -q
python -m camoufox path && python -m camoufox version
```

## Modes

* `WORKER_MODE=native|orchestrator` (default: native).

## Camoufox

* Браузер предзагружен в образе; `fetch` в рантайме **запрещён**.
* `CAMOUFOX_HEADLESS=virtual` по умолчанию; для задач можно переопределять.
* Диагностика: `python -m camoufox path`/`version`; health‑задача обязана проверять путь.

## Don’t

* Не менять пользователя контейнера; не выполнять `pip install`/`fetch` на проде.
* Не хранить секреты/прокси в репозитории.

