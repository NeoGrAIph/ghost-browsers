# AGENTS.md (runner)

## Commands
```bash
poetry install --no-root                     # prod зависимости + локальное .venv
poetry run ruff check .                     # линтинг (исправление через --fix)
poetry run pytest -q                        # unit/anyio/warm pool/VNC тесты
poetry run pytest tests/test_warm_pool.py -q
python -m camoufox path && python -m camoufox version
```

## Camoufox & warm pool

* Локальный docker-compose монтирует `config/warm-pool.local.json` и `browser-prefs.local.json` в `/etc/runner`. При изменении структур не забывайте синхронизировать оба файла.
* Контейнер собирается из `services/runner/Dockerfile` (Playwright base image, Poetry 1.8.3, установка `camoufox[geoip]==0.4.11`).
* При работе в рантайме `python -m camoufox fetch` запрещён — бинарь предзагружен во время сборки.
* `RunnerSettings` читает env: `RUNNER_ID`, `SLOT_LIMIT`, `WARM_POOL_MODE`, `WARM_POOL_CONFIG_PATH`, `BROWSER_PREFS_PATH`, `VNC_ENABLED`, `VNC_HTTP_BASE_URL`, `VNC_WS_BASE_URL`. Для compose дефолты прописаны в `docker-compose.yml` и `.env.example`.
* Smoke-проверки после `docker compose up --build`:
  * `curl http://localhost:8082/health` — warm pool статистика и путь к Camoufox.
  * `curl http://localhost:8082/workstations` — состояние прогретых слотов.
  * `curl http://localhost:8082/metrics` — Prometheus registry.

## Don’t

* Не менять пользователя контейнера (`pwuser`) и не устанавливать пакеты через `pip install`/`poetry add` внутри прод-образа.
* Не коммитить реальные warm pool конфиги — используйте `.local.json` пример.

## Notes

* Обновляйте `AGENT_NOTES.md` после каждого изменения warm pool, VNC пайплайна, событий и конфигурации.

