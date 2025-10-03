# Задание: Runner (FastAPI + Camoufox/Playwright)

## Цель
Управлять жизненным циклом браузерных сессий; публиковать события жизненного цикла в Gateway.

## Требования
- Памятный менеджер сессий; health (слот, VNC, прокси, ошибки prewarm, `camoufox_path`).
- Поддержка HTTP/SOCKS прокси на сессию; `start_url`, `start_url_wait`, warmup.
- noVNC/websockify интеграция; «тумблеры» браузера из смонтированного каталога.
- События: `session.created|updated|ended` в сторону Gateway (WS/SSE/HTTP заглушка).

## Качество
- Docstring/inline-комментарии; тесты на создание/удаление сессии (без реального браузера — заглушки).
- Обновить `AGENT_NOTES.md` (Interfaces/Decisions/TODO/How to Test).

## Сборка контейнера

1. Убедитесь, что Docker поддерживает BuildKit (`DOCKER_BUILDKIT=1`).
2. Соберите образ с предзагруженным Camoufox-браузером:

   ```bash
   docker build \
     -f services/runner/Dockerfile \
     -t ghost-runner:latest \
     .
   ```

   Образ использует wheel `camoufox[geoip]==0.4.11`, прогружает артефакты через `python -m camoufox fetch` **на этапе сборки** и запускается под `pwuser`.

3. Запуск локально:

   ```bash
   docker run --rm -p 8080:8080 ghost-runner:latest
   ```

   После старта проверьте окружение:

   ```bash
   curl http://localhost:8080/health | jq
   ```

   Ответ должен содержать `camoufox_path` со значением `/usr/bin/camoufox` и статус `ok`.

## Контракт `/health`

Эндпоинт `GET /health` должен возвращать JSON-структуру:

```json
{
  "status": "ok",
  "runner_id": "runner-name",
  "camoufox_path": "/usr/bin/camoufox",
  "slots": {"total": null, "active": 1, "available": null},
  "vnc": {
    "http_base_url": "http://localhost:9000/vnc",
    "ws_base_url": "ws://localhost:9000/vnc",
    "enabled": true
  },
  "proxy": {
    "enabled": false,
    "http_base_url": null,
    "https_base_url": null,
    "socks_base_url": null
  },
  "prewarm": {
    "failures": 0,
    "last_error": null
  }
}
```

Слоты рассчитываются из лимита настроек и текущего количества активных сессий. Раздел `prewarm` отражает последние ошибки предварительного прогрева браузера.
