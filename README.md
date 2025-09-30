# Camo-fleet

Минимальный набор сервисов для запуска Camoufox/Firefox сессий с live-просмотром через VNC.
Архитектура построена на sidecar-паттерне: воркер отвечает за API, а браузерный слой вынесен в отдельный
runner-контейнер. Репозиторий содержит четыре приложения и Kubernetes-манифесты для k3s кластера:

- **worker** — API-воркер, который проксирует запросы к локальному Camoufox runner'у и отдаёт `wsEndpoint`.
- **runner** — сервис, запускающий Camoufox и управляющий Playwright server'ом; выпускается в двух вариантах
  образов (headless и с VNC/noVNC).
- **vnc-gateway** — сервис, который проксирует HTTP/WebSocket трафик noVNC через фиксированный порт.
- **control-plane** — облегчённый оркестратор, проксирующий HTTP-запросы к воркерам и предоставляющий
  единый REST API для UI.
- **ui** — React SPA с панелью: список сессий, запуск новых и ссылки на WebSocket/VNC подключения.

## Возможности

- Direct-сессии (`wsEndpoint`) для Camoufox/Firefox (антидетект).
- TTL и авто-завершение простаивающих сессий.
- Простое round-robin распределение сессий между воркерами/runner'ами.
- Live-экран через VNC/noVNC слой (включается флагом для воркеров с поддержкой VNC).
- REST API без SSE/RBAC/Managed DSL — только базовые CRUD операции над сессиями.

## Структура

```
Camo-fleet/
├── control-plane/         # FastAPI control-plane
├── deploy/k8s/            # k3s-ready manifests
├── docker/                # Dockerfile'ы и entrypoint'ы
├── runner/                # Camoufox runner sidecar
├── ui/                    # Vite + React SPA
└── worker/                # API worker, проксирующий runner
```

## Локальный запуск

### Полностью в Docker (без Python на хосте)

1. Установите [Docker](https://docs.docker.com/get-docker/) и Docker Compose.
2. Запустите локальное окружение с дев-зависимостями:
   ```bash
   docker compose -f docker-compose.dev.yml up --build
   ```
   Будут собраны образы Camoufox runner'ов, воркеров, control-plane и UI. По умолчанию поднимаются два воркера:
   headless и VNC (с собственными runner sidecar'ами). Дополнительных зависимостей на хосте не нужно.
3. После запуска:
   - UI: `http://localhost:5173`
   - Control-plane API: `http://localhost:9000`
   - Headless worker API: `http://localhost:8080`
   - VNC worker API: `http://localhost:8081`
   - VNC gateway: `http://localhost:6080/vnc` — проксирует noVNC/ws трафик на нужный runner-порт
4. Тесты также можно прогнать внутри контейнеров:
   ```bash
   docker compose -f docker-compose.dev.yml run --rm --entrypoint pytest worker
   docker compose -f docker-compose.dev.yml run --rm --entrypoint pytest control-plane
   ```
   При необходимости дополнительные команды можно выполнять через `docker compose run --rm --entrypoint bash <service>`.

### Нативный запуск (опционально)

1. Установите Python 3.11+, Node.js 20+ и Docker.
2. Соберите runner sidecar (Camoufox):
   ```bash
   pip install -e runner/
   python -m camoufox fetch
   ```
3. Запустите runner:
   ```bash
   python -m camoufox_runner
   ```
   По умолчанию API доступен на `http://127.0.0.1:8070`.
4. Worker:
   ```bash
   cd worker
   python -m camofleet_worker
   ```
   По умолчанию API доступен на `http://127.0.0.1:8080`. Для работы с VNC необходим runner с поддержкой VNC
   (запускаемый из образа `Dockerfile.runner-vnc`).
5. Control-plane:
   ```bash
   cd control-plane
   python -m camofleet_control
   ```
   По умолчанию сервис слушает `http://127.0.0.1:9000`. Список воркеров задаётся переменной `CONTROL_WORKERS`
   (см. `control-plane/camofleet_control/config.py`).
6. UI:
   ```bash
   cd ui
   npm install
   npm run dev
   ```
   Для проксирования API можно переопределить `VITE_API_ORIGIN` (по умолчанию `http://localhost:9000`).

## Docker Desktop (Windows)

Ниже описан полностью контейнеризованный сценарий для Docker Desktop на Windows (WSL2 backend).

1. Установите [Docker Desktop](https://www.docker.com/products/docker-desktop/) и убедитесь, что включён режим Linux Containers.
2. Склонируйте репозиторий и откройте PowerShell/Terminal от имени пользователя:
   ```powershell
   cd path\to\Camo-fleet
   docker compose up --build
   ```
   Первая сборка займёт время (Playwright качает браузеры ~1–2 ГБ).
3. После старта сервисов:
   - UI: `http://localhost:8080`
   - Control-plane API: `http://localhost:9000`
   - VNC gateway: `http://localhost:6080/vnc` (UI подставляет `target_port` автоматически)
4. Для остановки окружения выполните:
   ```powershell
   docker compose down
   ```

## Docker-образы

Сборка образов (замените `REGISTRY` на собственный реестр):

```bash
docker build -t REGISTRY/camofleet-runner:latest -f docker/Dockerfile.runner .
docker build -t REGISTRY/camofleet-runner-vnc:latest -f docker/Dockerfile.runner-vnc .
docker build -t REGISTRY/camofleet-worker:latest -f docker/Dockerfile.worker .
docker build -t REGISTRY/camofleet-control:latest -f docker/Dockerfile.control .
docker build -t REGISTRY/camofleet-vnc-gateway:latest -f docker/Dockerfile.vnc-gateway .
docker build -t REGISTRY/camofleet-ui:latest -f docker/Dockerfile.ui .
```

Runner-образы содержат Camoufox + Playwright server: headless (`Dockerfile.runner`) и с VNC (`Dockerfile.runner-vnc`).
Worker-образ запускает только API (`python -m camofleet_worker`) и проксирует запросы в соседний runner.
UI-образ собирается в статический билд и обслуживается nginx с проксированием `/api` на control-plane.

## Kubernetes (k3s)

Манифесты расположены в `deploy/k8s`. Перед применением замените `REGISTRY/...` на ваши образы и
обновите `Ingress` хостнеймы. Затем выполните:

```bash
kubectl apply -k deploy/k8s
```

В результате будут созданы namespace `camofleet`, деплойменты/сервисы для всех компонентов и ingress с TLS.

## Переменные окружения

### Runner

| Переменная | Значение по умолчанию | Описание |
| ---------- | --------------------- | -------- |
| `RUNNER_VNC_WS_BASE` | `None` | Базовый адрес (со схемой, хостом и обычно путём `/vnc`) для генерации WebSocket URL предпросмотра. Если шлюз опубликован без префикса, путь можно опустить. |
| `RUNNER_VNC_HTTP_BASE` | `None` | Аналогично `RUNNER_VNC_WS_BASE`, но для noVNC iframe (`/vnc.html`). |
| `RUNNER_VNC_DISPLAY_MIN` / `RUNNER_VNC_DISPLAY_MAX` | `100` / `199` | Диапазон виртуальных `DISPLAY`, выделяемых Xvfb. |
| `RUNNER_VNC_PORT_MIN` / `RUNNER_VNC_PORT_MAX` | `5900` / `5999` | Диапазон TCP-портов для `x11vnc`. |
| `RUNNER_VNC_WS_PORT_MIN` / `RUNNER_VNC_WS_PORT_MAX` | `6900` / `6999` | Диапазон TCP-портов для websockify/noVNC. |
| `RUNNER_VNC_RESOLUTION` | `1920x1080x24` | Разрешение виртуального дисплея. |
| `RUNNER_VNC_WEB_ASSETS_PATH` | `/usr/share/novnc` | Путь к статике noVNC; если отсутствует, websockify раздаёт только WebSocket. |
| `RUNNER_VNC_LEGACY` | `0` | При значении `1` включает прежний режим с одним глобальным VNC-сервером (`vnc-start.sh`). |
| `RUNNER_PREWARM_HEADLESS` | `1` | Количество тёплых резервов без VNC (используется headless=true). |
| `RUNNER_PREWARM_VNC` | `1` | Количество тёплых резервов c VNC (Xvfb+x11vnc+websockify); автоматически отключается, если инструменты VNC недоступны в образе. |
| `RUNNER_PREWARM_CHECK_INTERVAL_SECONDS` | `2.0` | Период проверки/дополнения пула тёплых резервов. |
| `RUNNER_START_URL_WAIT` | `load` | Как долго ждать загрузку `start_url`: `none` (не грузить), `domcontentloaded`, `load`. При значении `none` навигация выполняется клиентом и стартовая вкладка останется пустой (включая VNC). |
| `RUNNER_DISABLE_IPV6` | `true` | Отключает IPv6 в профиле Firefox (`network.dns.disableIPv6`), чтобы не зависеть от поддержки IPv6 в инфраструктуре. |
| `RUNNER_DISABLE_HTTP3` | `true` | Полностью отключает HTTP/3 в Firefox (`network.http.http3.enable`, `network.http.http3.enable_0rtt`, `network.http.http3.enable_alt_svc`/`network.http.http3.alt_svc`, `network.http.http3.retry_different_host`, `network.dns.http3_echconfig.enabled`, `MOZ_DISABLE_HTTP3`), чтобы избежать ошибок TLS (`PR_END_OF_FILE_ERROR`) в средах без поддержки UDP/QUIC. |
| `RUNNER_DISABLE_WEBRTC` | `true` | Запрещает WebRTC в Firefox (`media.peerconnection.enabled=false`), исключая любые исходящие UDP-попытки (ICE/STUN) в кластерах с жёстким TCP-only egress. |
| `MOZ_DISABLE_HTTP3` | `1`, если `RUNNER_DISABLE_HTTP3=true` | Передаётся напрямую Firefox-процессам и гарантирует отключение HTTP/3 ещё до инициализации профиля. |
| `RUNNER_NETWORK_DIAGNOSTICS` | `["https://bot.sannysoft.com"]` | JSON-массив URL, которые runner проверяет при старте, фиксируя поддержку HTTP/2/HTTP/3 в текущей среде. |
| `RUNNER_DIAGNOSTICS_TIMEOUT_SECONDS` | `8.0` | Таймаут одной проверки в секундах; полезно уменьшить в средах с ограниченным доступом наружу. |

При включённых проверках эндпойнт `/health` runner'а дополняется секцией `diagnostics`, где отображается статус (`pending`, `complete`, `error` или `disabled`) и протоколы, успешно прошедшие проверку для каждого URL.

Порты и `DISPLAY` выделяются на каждую сессию. При использовании VNC gateway достаточно открыть сам шлюз (Docker: порт `6080`, Kubernetes: путь `/vnc`). По умолчанию публичные URL содержат префикс `/vnc` (например, `/vnc/{id}`), однако его можно поменять через `workerVnc.runnerPathPrefix` в Helm chart и соответствующие переменные окружения. Runner автоматически добавит `vnc.html` и `websockify` к базовому пути. Внутри сети контейнеры должны иметь доступ к диапазону `RUNNER_VNC_WS_PORT_MIN`–`RUNNER_VNC_WS_PORT_MAX`. Для headless‑резервов prewarm используется `headless=true`.

### Worker

| Переменная              | Значение по умолчанию | Описание                                   |
| ----------------------- | --------------------- | ------------------------------------------ |
| `WORKER_PORT`           | `8080`                | Порт HTTP API.                             |
| `WORKER_SESSION_DEFAULTS__HEADLESS` | `false` | Значение по умолчанию для headless.        |
| `WORKER_RUNNER_BASE_URL`| `http://127.0.0.1:8070` | Адрес sidecar runner'а внутри Pod/Compose. |
| `WORKER_SUPPORTS_VNC`   | `false`               | Помечает воркер как умеющий работать с VNC. |

### Control-plane

| Переменная         | Значение по умолчанию | Описание                                         |
| ------------------ | --------------------- | ------------------------------------------------ |
| `CONTROL_WORKERS`  | см. config            | JSON-массив с воркерами: `name`, `url`, `supports_vnc`, `vnc_ws`, `vnc_http`. |
| `CONTROL_PORT`     | `9000`                | Порт HTTP API.                                   |

### VNC gateway

| Переменная                | Значение по умолчанию | Описание |
| ------------------------- | --------------------- | -------- |
| `VNCGATEWAY_HOST`         | `0.0.0.0`             | Адрес, на котором слушает шлюз. |
| `VNCGATEWAY_PORT`         | `6080`                | Публичный порт HTTP/WebSocket. |
| `VNCGATEWAY_RUNNER_HOST`  | `runner-vnc`          | DNS-имя runner'а, доступного шлюзу. |
| `VNCGATEWAY_MIN_PORT`     | `6900`                | Минимальный websockify-порт, который может выдать runner. |
| `VNCGATEWAY_MAX_PORT`     | `6999`                | Максимальный websockify-порт. |
| `VNCGATEWAY_REQUEST_TIMEOUT` | `10.0`             | Таймаут HTTP-запросов к runner'у (сек). |

Значения Helm-чарта по умолчанию оставляют публичный порт шлюза (`workerVnc.gatewayPort=6080`) вне диапазона WebSocket-пулов (`workerVnc.vncPortRange.ws=6900-6909`). При рендеринге шаблон проверяет, что порт шлюза не пересекается ни с WebSocket-, ни с raw VNC-диапазонами, и завершает установку ошибкой, если ограничения нарушены.

UI не требует переменных окружения — все настройки кодируются в nginx.

## Тестирование

- `worker`: `pytest` — проверяет менеджер сессий и auto-cleanup.
- `control-plane`: `pytest` — покрытие round-robin логики.

Рекомендуемый (контейнерный) запуск:

```bash
docker compose -f docker-compose.dev.yml run --rm --entrypoint pytest worker
docker compose -f docker-compose.dev.yml run --rm --entrypoint pytest control-plane
```

Нативно:

```bash
cd worker && pip install -e .[dev] && pytest
cd control-plane && pip install -e .[dev] && pytest
```

## API

### Worker

- `GET /health` — состояние сервиса.
- `GET /sessions` — список активных сессий.
- `POST /sessions` — создание новой сессии. Поддерживает `vnc=true` для запроса VNC-предпросмотра, `start_url` и `start_url_wait` (при значениях `domcontentloaded` / `load` раннер откроет URL асинхронно, при `none` страница не будет загружена автоматически — например, VNC покажет пустой профиль, пока вы не перейдёте на адрес вручную).
- `GET /sessions/{id}` — детали, включая VNC ссылки, флаг `vnc_enabled` и режим ожидания `start_url_wait`.
- `POST /sessions/{id}/touch` — продлить TTL.
- `DELETE /sessions/{id}` — завершение.

### Control-plane

- `GET /workers` — статусы всех воркеров.
- `GET /sessions` — агрегированный список.
- `POST /sessions` — создать сессию на выбранном воркере или через round-robin (прокидывает `vnc`, `start_url` и `start_url_wait` дальше к воркерам и runner'у).
- `GET /sessions/{worker}/{id}` — детали.
- `DELETE /sessions/{worker}/{id}` — завершение.

## Лицензия

MIT.
