# Runner Parity Notes

## Implemented Concepts

- **FastAPI lifespan orchestration** – `app.main` wires `SessionManager.start()`
  and `.stop()` into the FastAPI lifespan, поэтому idle reaper, warm pool и
  Prometheus registry всегда синхронизированы со стартом/остановкой сервиса.【F:services/runner/app/main.py†L21-L122】
- **Validated configuration surface** – `RunnerSettings` парсит env, проверяет
  warm pool JSON, диапазоны VNC портов и опции прокси/прогрева, предотвращая
  запуск с некорректными параметрами.【F:services/runner/app/config/settings.py†L30-L208】
- **Hybrid warm pool acquisition** – `SessionManager.create_session` сначала
  резервирует прогретый слот, а при нехватке переключается на cold launch и
  фиксирует источник браузера в `browser_origin`.【F:services/runner/app/session_manager.py†L196-L369】
- **Process-backed VNC orchestration** – `ProcessVncController` управляет Xvfb,
  x11vnc и websockify, выдаёт `SessionVncDetails` и гарантирует освобождение
  портов при завершении сессии.
- **Prewarm navigation & TTL metrics** – `WarmPoolManager` выполняет навигацию
  и ведёт статистику, а `/health` отражает тайминги reaper'а и ошибки прогрева.
- **Sanitised VNC payloads** – Runner очищает пользовательские VNC токены, чтобы
  gateway выдавал собственные HMAC JWT.

## Recent parity improvements

- Browser network hardening flags supplied by the worker (for example
  disabling HTTP/3/Alt-Svc via `MOZ_DISABLE_HTTP3`) are now honoured during cold
  launches and warm pool provisioning through `RunnerSettings.browser_required_flags`.
- Docker image на Playwright 1.55 предустанавливает локали, Windows-compatible
  fonts и утилиты Xvfb/x11vnc/websockify/noVNC, обеспечивая паритет с production
  thick-образом.【F:services/runner/Dockerfile†L1-L84】
- Локальный docker compose монтирует демонстрационные warm pool JSON/профили и
  включает `WARM_POOL_MODE=hybrid`, что позволяет cold сессиям запускаться при
  нехватке прогретых слотов.【F:docker-compose.yml†L7-L58】【F:services/runner/config/warm-pool.local.json†L1-L15】
