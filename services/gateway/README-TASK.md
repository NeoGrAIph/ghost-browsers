# Задание: Gateway (FastAPI)

## Цель
Реализовать публичный фронт (REST/SSE/WebSocket): управление сессиями, выдача VNC-токенов, приём событий от Runner.

## Требования
- Аутентификация через Keycloak (валидация JWT по JWKS). Логировать sub/email в audit trail.
- Стейтлес; карта `session_id→runner` восстанавливается при старте через опрос Runner.
- REST: POST/GET/GET by id/DELETE `/sessions`, POST `/sessions/{id}/proxy`, POST `/sessions/{id}/touch`, GET `/runners`.
- События: ретрансляция в UI через SSE `/events` и WS `/events/ws`.
- Токены VNC: короткоживущие JWT, TTL ≤ 300 сек.
- Конфигурация: `DISCOVERY_MODE`, `RUNNERS`, `JWT_JWKS_URL`, `VNC_TOKEN_TTL_SEC`.

## Качество и сопровождение
- Docstring у каждого эндпоинта/сервиса; inline-комментарии над нетривиальной логикой.
- Юнит-тесты: CRUD сессий (в памяти), генерация VNC-токенов (подпись заглушкой), SSE заглушка.
- Обновить `AGENT_NOTES.md`: Interfaces, Decisions, Known Gaps, How to Test.
