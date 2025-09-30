# Задание: Runner (FastAPI + Playwright/Firefox)

## Цель
Управлять жизненным циклом браузерных сессий; публиковать события жизненного цикла в Gateway.

## Требования
- Памятный менеджер сессий; health-эндпоинт (слот, VNC, прокси, ошибки prewarm).
- Поддержка HTTP/SOCKS прокси на сессию; `start_url`, `start_url_wait`, warmup.
- noVNC/websockify интеграция; приём «тумблеров» браузера из смонтированного каталога.
- События: `session.created|updated|ended` в сторону Gateway (WS/SSE/HTTP заглушка).

## Качество
- Docstring/inline-комментарии; тесты на создание/удаление сессии (без реального браузера — заглушки).
- Обновить `AGENT_NOTES.md` (Interfaces/Decisions/TODO/How to Test).
