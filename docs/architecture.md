# Ghost-browsers — Архитектура (lean)

## Обзор
Платформа управляет одноразовыми Camoufox-сессиями с live-доступом (noVNC/WebSocket) и индивидуальными прокси. UI предоставляет мониторинг и операции; внешние клиенты используют REST/SSE.

## Компоненты
- **Session Runner** — хранит сессии в памяти, управляет Playwright/Firefox, пушит события в Gateway.
- **Session Gateway** — REST/SSE/WebSocket API, проверка Keycloak JWT, карта `session_id → runner`, WebSocket прокси `/sessions/{id}/ws`.
- **VNC Gateway** — прокси для VNC/WebSocket; валидирует короткоживущие токены.
- **UI** — React+Vite SPA: Keycloak auth, список сессий, состояние runner’ов, VNC просмотр.

## Контракты создания сессий
- UI отправляет `POST /sessions` в Gateway. Сервис выбирает подходящий runner из
  текущего пула и проксирует запрос `SessionCreatePayload`, не раскрывая Runner во
  внешнюю сеть. Ответ Runner нормализуется и одновременно регистрируется в
  in-memory реестре Gateway.

## Нефункциональные требования
- Время запуска «тёплой» сессии ≤ 4 сек.
- SLA событий: < 2 сек до доставки в UI.