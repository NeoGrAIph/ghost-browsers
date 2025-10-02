# AGENT_NOTES — UI

## Overview
Консоль оператора Ghost Browsers на React + Vite. Обеспечивает авторизацию через Keycloak, отображение списка сессий браузера, просмотр деталей/снимков и управление (создание/удаление).

## Interfaces
- **REST**: `/sessions` (GET/POST/DELETE) через `api/client.ts`.
- **REST команды**: `/sessions/commands` (POST/PATCH/DELETE) — создаём/обновляем/завершаем сессии через Runner-клиент.
- **REST здоровье**: `/runners` (GET) — `fetchRunners` возвращает `RunnerStatus` для сайдбара и динамического composer.
- **SSE**: `/events` — автообновление списка сессий, перезапуск с экспоненциальной задержкой;
  bearer-токен пробрасывается как query `access_token` для нативного `EventSource`.
- **VNC**: встраивание внешнего URL `session.vncUrl` в `iframe`.

## Data & Models
- `Session`/`SessionEvent` описаны в `types/session.ts` (Zod схемы) и адаптеры `adaptSession*`
  нормализуют snake_case FastAPI payload в camelCase модель UI (добавляют `region`,
  `proxyId`, `proxyLabel`, `snapshotUrl`). `adaptSession` теперь выбирает прямой
  `wsEndpoint` при наличии и прокидывает fallback `publicWsEndpoint` для случаев,
  когда до runner'а нет прямого доступа.
- Состояние фильтров в `store/sessionFilters.ts` (Zustand).

## Decisions
- Keycloak PKCE: `AuthProvider` и `silent-check-sso.html` для фоновой проверки SSO.
- React Query как единый слой данных (`queryKeys.sessions`) + интеграция с SSE (`useSessionEvents`).
- UI-паттерн split-view: сетка карточек слева, подробности справа.
- Локальная тема (light/dark) через `ThemeProvider` с `localStorage`.
- Команда создания формирует payload (`browserName`, `region`, `proxyId`, `runnerId?`) на базе выбранных справочников; при отсутствии явного `runnerId` подбор выполняет Gateway.
- Worker статус-панель повторно использует те же данные `/runners`, что и composer, для единого источника правды.
- Состояние `SessionComposerValues` хранит дополнительные поля (`headless`, `idleTtlSeconds`, `startUrl*`, `proxy*`), чтобы API-адаптер мог формировать полный payload Runner даже до появления соответствующего UI.

## Constraints & Invariants
- Все сетевые вызовы через `ApiClient` (`fetch` + Zod валидация).
- SSE обязателен для консистентного кеша React Query.
- `SessionComposer` отправляет минимум (`browserName`, `region`, `proxyId?`) и при явном выборе прокидывает `runnerId`.
- Токен Keycloak обновляется каждые 20 сек. и при событии `onTokenExpired`.

## Known Gaps / TODO
- [x] Реальные справочники браузеров/регионов/прокси брать с backend вместо захардкоженных значений (через `/runners` + агрегацию `buildSessionComposerData`).
- [ ] Поддержать обновление прокси существующей сессии (UI + endpoint).
- [ ] Покрыть компонентные сценарии (SessionToolbar/Dashboard) тестами RTL.
- [x] Реализовать обработку ошибок SSE (баннер, кнопка повторного подключения).
- [ ] Визуализировать выбор раннера в composer, когда на бэке появится стратегия балансировки.

## How to Test
- `pnpm -C apps/ui lint`
- `pnpm -C apps/ui test`
- `pnpm -C apps/ui dev` — локальный просмотр (требуются переменные VITE_GATEWAY_URL/Keycloak).

## Changelog (for agents)
- 2024-09-08 · gpt-5-codex · Начальная реализация консоли: авторизация, список/детали сессий, создание/удаление, SSE, темы, базовые тесты.
- 2024-09-09 · gpt-5-codex · Перешли на модели core.Session/core.SessionEvent: адаптеры в
  `types/session.ts`, хранение списка сессий напрямую в React Query, обновлены фильтры,
  компоненты и тесты под статусы `INIT/READY/TERMINATING/DEAD`.
- 2024-09-10 · gpt-5-codex · Переключили SSE на `/events`, пробрасываем токен через `access_token`, добавлен vitest для клиента.
- 2024-09-11 · gpt-5-codex · Перевели UI на командные эндпоинты `/sessions/commands`, покрыли DashboardPage сценарии создания/удаления.
- 2025-03-17 · gpt-5-codex · Интегрированы `/runners` в UI: динамический SessionComposer, статус-панель воркеров, тесты на загрузку/ошибки и фильтрацию раннеров.
- 2025-10-14 · gpt-5-codex · UI принимает `ws_public_endpoint`, хранит обе ссылки на WebSocket и по умолчанию использует прямой `wsEndpoint`.
- 2025-10-02 · gpt-5-codex · Добавлен стор для отслеживания SSE, обработка превышения ретраев и баннер повторного подключения.
- 2025-10-15 · gpt-5-codex · Синхронизировали модель `SessionComposerValues` с адаптером создания сессий, устранив lint-ошибки по небезопасным полям.
