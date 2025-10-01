# AGENT_NOTES — UI

## Overview
Консоль оператора Ghost Browsers на React + Vite. Обеспечивает авторизацию через Keycloak, отображение списка сессий браузера, просмотр деталей/снимков и управление (создание/удаление).

## Interfaces
- **REST (Gateway)**: `GET /sessions`, `POST /sessions`, `DELETE /sessions/{id}` — через `api/client.ts`.
- **SSE**: `/sessions/stream` — автообновление списка сессий, перезапуск с экспоненциальной задержкой.
- **VNC**: встраивание внешнего URL `session.vncUrl` в `iframe`.

## Data & Models
- `Session`/`SessionEvent` описаны в `types/session.ts` (Zod схемы); адаптеры `adaptSession*`
  нормализуют snake_case FastAPI payload в camelCase модель UI и добавляют производные поля
  (`region`, `proxyId`, `proxyLabel`, `snapshotUrl`).
- Состояние фильтров в `store/sessionFilters.ts` (Zustand).

## Decisions
- Keycloak PKCE: `AuthProvider` и `silent-check-sso.html` для фоновой проверки SSO.
- React Query как единый слой данных (`queryKeys.sessions`) + интеграция с SSE (`useSessionEvents`).
- UI-паттерн split-view: сетка карточек слева, подробности справа.
- Локальная тема (light/dark) через `ThemeProvider` с `localStorage`.
- Создание сессий идёт через Gateway `POST /sessions`: UI собирает полный `SessionCreatePayload`,
  Gateway выбирает runner, проксирует запрос и регистрирует ответ без раскрытия runner наружу.

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
- 2024-09-08 · gpt-5-codex · Начальная реализация консоли: авторизация, список/детали сессий, создание/удаление, SSE, темы, базовые тесты.
- 2024-09-09 · gpt-5-codex · Перешли на модели core.Session/core.SessionEvent: адаптеры в `types/session.ts`, хранение списка сессий напрямую в React Query, обновлены фильтры, компоненты и тесты под статусы `INIT/READY/TERMINATING/DEAD`.
- 2024-10-08 · gpt-5-codex · UI формирует Runner `SessionCreatePayload`, добавлены расширенные поля композитора, адаптер core→view и покрывающие тесты.
- 2024-10-10 · gpt-5-codex · Синхронизированы адаптеры с актуальными схемами core, удалён временный mapper, `POST /sessions` теперь бьётся о gateway-прокси, обновлены тесты и документация.
