# AGENT_NOTES — UI

## Overview
Консоль оператора Ghost Browsers на React + Vite. Обеспечивает авторизацию через Keycloak, отображение списка сессий браузера, просмотр деталей/снимков и управление (создание/удаление).

## Interfaces
- **REST (Gateway)**: `GET /sessions`, `POST /sessions`, `DELETE /sessions/{id}` — через `api/client.ts`.
- **SSE**: `/sessions/stream` — автообновление списка сессий, перезапуск с экспоненциальной задержкой.
- **VNC**: встраивание внешнего URL `session.vncUrl` в `iframe`.

## Data & Models
- `Session`/`SessionEvent` описаны в `types/session.ts` (Zod схемы).
- Состояние фильтров в `store/sessionFilters.ts` (Zustand).

## Decisions
- Keycloak PKCE: `AuthProvider` и `silent-check-sso.html` для фоновой проверки SSO.
- React Query как единый слой данных (`queryKeys.sessions`) + интеграция с SSE (`useSessionEvents`).
- UI-паттерн split-view: сетка карточек слева, подробности справа.
- Локальная тема (light/dark) через `ThemeProvider` с `localStorage`.
- Создание сессий идёт через Gateway `POST /sessions`, который сам выбирает runner и скрывает внутреннюю топологию.

## Constraints & Invariants
- Все сетевые вызовы через `ApiClient` (`fetch` + Zod валидация).
- SSE обязателен для консистентного кеша React Query.
- `SessionComposer` собирает полный `SessionCreatePayload` (headless/TTL/start_url/proxy/metadata).
- Токен Keycloak обновляется каждые 20 сек. и при событии `onTokenExpired`.

## Known Gaps / TODO
- [ ] Реальные справочники браузеров/регионов/прокси брать с backend вместо захардкоженных значений.
- [ ] Поддержать обновление прокси существующей сессии (UI + endpoint).
- [ ] Покрыть компонентные сценарии (SessionToolbar/Dashboard) тестами RTL.
- [ ] Реализовать обработку ошибок SSE (баннер, кнопка повторного подключения).

## How to Test
- `pnpm -C apps/ui lint`
- `pnpm -C apps/ui test`
- `pnpm -C apps/ui dev` — локальный просмотр (требуются переменные VITE_GATEWAY_URL/Keycloak).

## Changelog (for agents)
- 2024-09-08 · gpt-5-codex · Начальная реализация консоли: авторизация, список/деталей сессий, создание/удаление, SSE, темы, базовые тесты.
- 2024-10-08 · gpt-5-codex · UI формирует Runner `SessionCreatePayload`, добавлены расширенные поля композитора, адаптер core→view и покрывающие тесты.
- 2024-10-09 · gpt-5-codex · Переключили создание сессий на Gateway `POST /sessions`, убрали прямой доступ UI к Runner.
