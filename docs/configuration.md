# Конфигурация и переменные окружения (lean)

## Общие
- `KEYCLOAK_REALM` / `KEYCLOAK_URL` / `KEYCLOAK_CLIENT_ID`

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