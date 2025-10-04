# AGENTS.md (ui)
## Commands
```bash
pnpm install --frozen-lockfile          # устанавливает workspace зависимости
pnpm -C apps/ui lint                    # eslint + stylelint правила
pnpm -C apps/ui test                    # vitest + jsdom
pnpm -C apps/ui build                   # prod bundle для nginx образа
```

## Local notes

* Vite переменная `VITE_GATEWAY_URL` задаётся во время сборки Docker образа (`apps/ui/Dockerfile`). Для docker compose используется `/api`, проксируемый Nginx в gateway.
* Основные модули: `src/api/gateway.ts` (REST/SSE клиенты), `src/store/sessionStore.ts` (Zustand), `src/components/VncViewer` (noVNC iframe).
* После `docker compose up --build` UI доступен на `http://localhost:8081`. Проверка API: `fetch('/api/health')` в DevTools → отвечает gateway `200`.
* При изменении публичного API не забывайте синхронизировать типы в `src/types` и документацию (`docs/ui`, `READMI.md`).

