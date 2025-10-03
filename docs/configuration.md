# Конфигурация и переменные окружения (lean)

## Общие
- `KEYCLOAK_REALM` / `KEYCLOAK_URL` / `KEYCLOAK_CLIENT_ID`

## Локальный запуск через docker compose

Для локального развёртывания предусмотрен стек `docker-compose.yml`, который собирает `runner`, `gateway`, `vnc-gateway` и UI в
одном origin. Прогретый пулл Runner'а — это **парк отдельных рабочих станций**: каждая станция описана в `services/runner/config/warm-pool.local.json`, имеет собственный `fingerprint_id`, набор `tags` и относительный путь до набора браузерных тумблеров (`prefs_rel_path`). Файл `services/runner/config/browser-prefs.local.json` содержит сами тумблеры; он монтируется внутрь Runner'а и используется как базовый каталог (`CAMOUFOX_PREFS_BASE_PATH`), чтобы прогретые и холодные сессии разделяли одинаковый профиль.

1. Скопируйте `.env.example` в `.env` и при необходимости скорректируйте значения. Переменная `VNC_TOKEN_SECRET` **обязана** быть
   одинаковой для `gateway` и `vnc-gateway`, иначе токены, выдаваемые `VncTokenService`, не пройдут проверку `TokenValidator`.
   Шаблоны публичных VNC URL, которые перечислены в `RUNNERS`, также должны ссылаться на тот же хост, что и опубликованный порт
   `vnc-gateway` (по умолчанию `http://localhost:8001`). `SLOT_LIMIT` в `.env` и `total_slots` в `RUNNERS` должны совпадать с числом
   рабочих станций, перечисленных в `warm-pool.local.json`, чтобы Gateway показывал реальную вместимость парка. Режим
   `WARM_POOL_MODE=hybrid` сохраняет приоритет за прогретым парком, но позволяет Runner'у автоматически запускать холодные
   браузеры, когда свободных прогретых слотов не осталось.
2. При необходимости отредактируйте `services/runner/config/warm-pool.local.json`, добавив или удалив рабочие станции, и синхронизируйте
   для них `fingerprint_id`, `tags` и `prefs_rel_path`. Новые наборы тумблеров добавляйте в `services/runner/config/browser-prefs.local.json` — Runner смонтирует файл в `/etc/runner/browser-prefs.json` и передаст путь Camoufox при запуске прогретых и холодных браузеров.
3. Запустите `docker compose up --build`. Стек пробрасывает порты `8081` (UI с Nginx и проксированным API `/api`), `8080`
   (gateway), `8082` (прямой доступ к runner для отладки) и `8001` (VNC gateway).
4. При добавлении новых runner'ов обновляйте переменную `RUNNERS` в `docker-compose.yml`, указывая уникальный `id`, `base_url` и
   соответствующие публичные шаблоны `vnc_http_url_template`/`vnc_ws_url_template`. Все записи обязаны использовать общий
   `VNC_TOKEN_SECRET` и ссылаться на корректные публичные адреса `vnc-gateway`, чтобы UI мог построить рабочие ссылки `SessionVncDetails`.

> Примечание: UI внутри контейнера обслуживается Nginx конфигурацией `apps/ui/nginx.conf`, которая проксирует `/api/` в gateway,
> обеспечивая единый origin и корректную работу REST/SSE/WebSocket вызовов без CORS middleware.

## Gateway
- `DISCOVERY_MODE` = `k8s` | `static`
- `RUNNERS` — список `host:port` при static
- `JWT_JWKS_URL` — публичный JWKS Keycloak
- `VNC_TOKEN_TTL_SEC` (<= 300)
- `GATEWAY_TRUSTED_CIDRS` — через запятую; список подсетей (IPv4/IPv6), из которых
  запросы считаются «внутренними» и не требуют аутентификации. Пустые элементы
  запрещены. Пример: `10.0.0.0/8,fd00::/64`.
- `GATEWAY_TRUSTED_HEADER` — (опционально) имя заголовка, который может выставлять
  ingress/sidecar с оригинальным IP-адресом клиента. Поддерживаются списки вида
  `"10.1.2.3, 192.0.2.10"`; берётся первый валидный IP. Если заголовок отсутствует
  или не содержит корректного адреса, применяется проверка токена.

## Runner
- `HTTP_PROXY`, `HTTPS_PROXY`, `SOCKS_PROXY` — индивидуальные прокси
- `START_URL`, `START_URL_WAIT_MS`, `WARMUP`
- `BROWSER_PREFS_PATH` — путь к «тумблерам» (ConfigMap/Secret)
- `CAMOUFOX_HEADLESS=virtual` (по умолчанию)
- (Опционально) `XDG_CACHE_HOME` — общий кэш, если потребуется

## UI
- `VITE_GATEWAY_URL` — базовый URL Gateway для REST/SSE (включая `POST /sessions`)

## VNC Gateway
- `VNC_GATEWAY_RUNNER_HTTP_BASE` — базовый HTTP URL Runner'а, к которому
  проксируются REST-запросы (по умолчанию `http://runner:8080`).
- `VNC_GATEWAY_RUNNER_WS_BASE` — базовый WebSocket URL Runner'а для прокси
  VNC-туннелей (по умолчанию `ws://runner:8080`).
- `VNC_GATEWAY_TOKEN_SECRET` — общий секрет для проверки HMAC-токенов, который
  Gateway использует совместно с VNC Gateway (по умолчанию `dev-secret`).
- `VNC_GATEWAY_METRICS_BACKEND` — `prometheus` (значение по умолчанию) или
  `otlp`; определяет куда отправляются метрики соединений.
- `VNC_GATEWAY_METRICS_REGISTRY_IMPORT` — `module:attribute` с существующим
  `CollectorRegistry`, если Prometheus-метрики нужно собирать в общую
  регистрацию.
- `VNC_GATEWAY_METRICS_OTLP_EXPORTER_IMPORT` — `module:attribute`, возвращающий
  OTLP-экспортёр, когда `VNC_GATEWAY_METRICS_BACKEND=otlp`.

> Секреты не хранятся в VCS. Используйте `.env` локально и Secret в k3s.

## Helm deployment

Набор чарта для control-plane компонентов расположен в `docs/helm/platform`. Он
собирает Deployments/Services/Ingress для `gateway`, `runner`, `vnc-gateway`,
`ui` и `camoufox-worker`, поддерживает передачу переменных окружения и Secret-
значений (например, `VNC_TOKEN_SECRET`, Keycloak client secret, токены Camoufox).

1. Подготовьте namespace и базовые Secret'ы:

   ```bash
   kubectl create namespace ghost
   kubectl create secret generic gateway-keycloak \
     --namespace ghost \
     --from-literal=clientSecret=... && \
   kubectl create secret generic gateway-vnc \
     --namespace ghost \
     --from-literal=token=...
   ```

   Аналогично создайте секреты для Runner (`camoufox-credentials`), UI
   (`ui-keycloak`), camoufox-worker (`worker-gateway-token`) и т.д. либо
   подключите существующие Secret'ы через `extraEnvFromSecrets`.

2. Выберите значения для окружения. В каталоге `docs/helm/platform` приведены
   примеры (`gateway.values.yaml`, `runner.values.yaml`, `vnc-gateway.values.yaml`,
   `ui.values.yaml`, `camoufox-worker.values.yaml`). Их можно комбинировать или
   использовать как шаблон для собственного файла.

3. Установите релиз Helm, передав необходимые overrides:

   ```bash
   helm install ghost ./docs/helm/platform \
     --namespace ghost --create-namespace \
     -f docs/helm/platform/values.yaml \
     -f docs/helm/platform/gateway.values.yaml \
     -f docs/helm/platform/runner.values.yaml \
     -f docs/helm/platform/vnc-gateway.values.yaml \
     -f docs/helm/platform/ui.values.yaml \
     -f docs/helm/platform/camoufox-worker.values.yaml
   ```

   Для обновления конфигурации используйте `helm upgrade ghost ./docs/helm/platform -f ...`.

4. Проверяйте состояние релиза стандартными командами Helm/Kubernetes:

   ```bash
   helm status ghost -n ghost
   kubectl get pods,svc,ingress -n ghost
   ```

> Чарт не создаёт Secret'ы автоматически — их нужно подготовить заранее или
> подключить существующие через `secretEnv`/`extraEnvFromSecrets`.