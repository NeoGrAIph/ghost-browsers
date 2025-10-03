# Ghost Browsers UI

## Overview
Операторская консоль Ghost Browsers собрана на React + Vite. Приложение обращается к Gateway REST API и событиям SSE, отображая сессии браузеров и позволяя управлять ими.

## Installation & Local Commands
```bash
pnpm install
pnpm -C apps/ui lint
pnpm -C apps/ui test
pnpm -C apps/ui dev
pnpm -C apps/ui build
```

## Environment Variables
| Переменная | Назначение | Где применяется | Значение по умолчанию |
|------------|------------|-----------------|-----------------------|
| `VITE_GATEWAY_URL` | Базовый URL публичного Gateway (REST + SSE). Подставляется в `import.meta.env.VITE_GATEWAY_URL` и вшивается в скомпилированный фронтенд. | Сборка (`pnpm -C apps/ui build`) и докер-образ. | Нет, **обязательна**. |

> [!NOTE]
> Значение `VITE_GATEWAY_URL` вычисляется на этапе сборки. Для локальной разработки его можно определить в `.env.local`, а при сборке Docker-образа передать через `--build-arg VITE_GATEWAY_URL="https://gateway.example.com"`.

## Docker Image
Сборка реализована в `apps/ui/Dockerfile` и строится через `make ui-image`, который предварительно запускает линтер и тесты.

```bash
make ui-image UI_IMAGE=ghcr.io/<org>/ui:dev \
  UI_EXTRA_BUILD_ARGS="--build-arg VITE_GATEWAY_URL=https://gateway.example.com"
```

Полученный образ — статический nginx-сервер (`EXPOSE 80`) с содержимым каталога `dist`.

## CI
Workflow `.github/workflows/ui-image.yml` автоматически пересобирает и публикует образ в GHCR:
1. Устанавливает зависимости (`pnpm install`).
2. Запускает `make ui-image` (lint → test → docker build).
3. Публикует образ `ghcr.io/<owner>/ui:<tag>`.

Тег задаётся вручную в `workflow_dispatch` либо равен текущему SHA при пуше в `main`.
