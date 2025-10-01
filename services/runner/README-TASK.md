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

## Контракт `/health`

Эндпоинт `GET /health` должен возвращать JSON-структуру:

```json
{
  "status": "ok",
  "runner_id": "runner-name",
  "camoufox_path": "/usr/bin/camoufox",
  "slots": {"total": 3, "active": 1, "available": 2},
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
