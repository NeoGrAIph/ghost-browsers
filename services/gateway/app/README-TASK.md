# Структура исходников Gateway
- `app/main.py` — сбор FastAPI-приложения (routers, deps, lifespan).
- `app/routers/sessions.py` — CRUD сессий; `runners.py` — список раннеров.
- `app/deps/security.py` — валидация Keycloak JWT.
- `app/services/*` — внутренняя логика (карта сессий, discovery, токен-сервис).
