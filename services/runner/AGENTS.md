# AGENTS.md (runner)

## Commands
```bash
poetry install --no-root
poetry run ruff check .
poetry run pytest -q
python -m camoufox path && python -m camoufox version
```

## Camoufox

* Браузер предзагружен в базовом образе; `fetch` в рантайме запрещён.
* Headless по умолчанию: `CAMOUFOX_HEADLESS=virtual`.
* Диагностика: команды выше; `GET /health` должен возвращать `camoufox_path`.

## Don’t

* не менять пользователя контейнера; не вызывать `pip install`/`fetch` на проде.

## Notes

* Реализация не включена. См. `README-TASK.md`.
* Обновляйте `AGENT_NOTES.md` при каждом значимом изменении.

```
