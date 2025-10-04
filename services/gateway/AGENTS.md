# AGENTS.md (gateway)

## Commands
```bash
poetry install --no-root           # создаёт .venv с prod зависимостями
poetry run ruff check .            # линтинг (исправление через --fix)
poetry run pytest -q               # unit + anyio тесты (MockTransport для внешних вызовов)
poetry run pytest tests/routers -q # таргетные проверки REST/SSE/WS маршрутов
```

## Local notes

* Конфигурация читается из env (`GatewaySettings.from_env`). Для docker compose все переменные заданы в `docker-compose.yml` и `.env.example`.
  * `RUNNERS` — JSON список раннеров; для локального стека шаблоны VNC URL указывают на `http://localhost:8001` / `ws://localhost:8001`.
  * `GATEWAY_TRUSTED_CIDRS` по умолчанию `0.0.0.0/0`, поэтому локальные HTTP/WS запросы проходят без JWT.
  * `VNC_TOKEN_SECRET` обязан совпадать с `services/vnc-gateway`.
* Lifespan запускает discovery и фоновые health-пробы. При изменении фоновых задач обновляйте `AGENT_NOTES.md` (раздел *Decisions*).
* Docker образ собирается `docker build -f services/gateway/Dockerfile .` или `make gateway-image`. Запуск через `uvicorn app.main:create_app --host 0.0.0.0 --port 8080`.
* После поднятия стека `docker compose up --build` smoke-проверки:
  * `curl http://localhost:8080/runners` — список раннеров с health-флагами.
  * `curl http://localhost:8080/workstations` — warm pool из runner через события.
  * `curl -N http://localhost:8080/events` — SSE поток (в dev без токена, иначе требуется Bearer JWT).

## Testing tips

* SSE/WS тесты используют `anyio`. При добавлении новых маршрутов придерживайтесь `tests/routers/test_events.py` / `test_sessions.py` паттернов.
* Обновляйте `AGENT_NOTES.md` при каждом значимом изменении (конфигурация, события, discovery, токены).

