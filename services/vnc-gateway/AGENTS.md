# AGENTS.md (vnc-gateway)

## Commands
```bash
poetry install --no-root            # prod зависимости
poetry run ruff check .            # линтинг
poetry run pytest -q               # unit/async тесты токенов и прокси
poetry run pytest tests/test_routes.py -q
```

## Local notes

* Конфигурация задаётся env (см. `camou_vnc_gateway.config.Settings`). В docker compose значения прокидываются автоматически:
  * `VNC_GATEWAY_RUNNER_HTTP_BASE` / `WS_BASE` → `http://runner:8080` / `ws://runner:8080`.
  * `VNC_GATEWAY_TOKEN_SECRET` должен совпадать с `gateway`.
* Эндпоинты: `GET /sessions/{id}` (HTTP прокси), `WS /sessions/{id}/ws`, `GET /metrics`.
* После `docker compose up --build` проверяйте `curl -I http://localhost:8001/sessions/<id>?token=...` и `curl http://localhost:8001/metrics`.
* Docker образ строится `docker build -f services/vnc-gateway/Dockerfile .`.

## Notes

* Обновляйте `AGENT_NOTES.md` при изменениях токенов, прокси или метрик.

