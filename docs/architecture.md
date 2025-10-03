# Ghost-browsers — Архитектура (lean)

## Обзор
Платформа управляет одноразовыми Camoufox-сессиями с live-доступом (noVNC/WebSocket) и индивидуальными прокси. UI предоставляет мониторинг и операции; внешние клиенты используют REST/SSE.

## Компоненты
- **Session Runner** — хранит сессии в памяти, управляет Playwright/Firefox, пушит события в Gateway.
- **Session Gateway** — REST/SSE/WebSocket API, проверка Keycloak JWT, карта `session_id → runner`, WebSocket прокси `/sessions/{id}/ws`.
- **VNC Gateway** — прокси для VNC/WebSocket; валидирует короткоживущие токены.
- **UI** — React+Vite SPA: Keycloak auth, список сессий, состояние runner’ов, VNC просмотр.

## Безопасность и зоны доверия
- **Внутри кластера Kubernetes** (между Gateway, Runner, VNC Gateway и служебными джобами)
  действует модель полного доверия: сервисы должны иметь возможность обращаться к
  REST/SSE/WS API Gateway без выдачи Keycloak-токенов. Авторизация внутри кластера
  обеспечивается сетевой сегментацией (ClusterIP, NetworkPolicy) и будущей поддержкой
  белых списков CIDR на стороне Gateway.
- **Публичный периметр** (Ingress/Load Balancer, UI) по-прежнему требует аутентификацию
  пользователя через Keycloak и валидацию VNC-токенов. Gateway обязан строго проверять
  токены для входящих соединений, которые поступают с внешних IP/через ingress.
- Требуется реализовать конфигурационный механизм, позволяющий задавать список
  доверенных подсетей/заголовков для внутренних клиентов и покрыть сценарии HTTP/SSE/WS
  (см. `services/gateway/AGENT_NOTES.md` для задач по реализации).

## Контракты создания сессий
- UI отправляет `POST /sessions` в Gateway. Сервис выбирает подходящий runner из
  текущего пула и проксирует запрос `SessionCreatePayload`, не раскрывая Runner во
  внешнюю сеть. Ответ Runner нормализуется и одновременно регистрируется в
  in-memory реестре Gateway.

## Контрольные WebSocket-каналы
- Runner всегда возвращает прямой Playwright endpoint в поле `ws_endpoint`.
  Клиенты внутри кластера должны использовать его напрямую для минимальной
  задержки и обхода лишних прокси.
- Gateway и worker регистрируют проксируемый путь `ws_public_endpoint`, который
  публикуется как `/sessions/{id}/ws`. Это значение служит резервным каналом,
  когда прямое соединение с Runner невозможно (ingress, NAT, ограниченные ACL).
- UI и автоматизация принимают оба значения и выбирают прямой endpoint при
  доступности, возвращаясь к `ws_public_endpoint`, если проброс недоступен.

## Нефункциональные требования
- Время запуска «тёплой» сессии ≤ 4 сек.
- SLA событий: < 2 сек до доставки в UI.

## Контур доставки runner-образа
- **Локальная сборка**: `make runner-image` использует BuildKit (`docker buildx build --load`) и
  запускает smoke-последовательность внутри только что собранного контейнера. Внутри
  контейнера выполняются `poetry check`, установка dev-зависимостей (`poetry install --with dev --no-root`),
  `PYTHONPATH=. poetry run pytest -q`, а также диагностика Camoufox (`python -m camoufox path` и
  `python -m camoufox version`). Это гарантирует, что production-образ совместим с тестами без
  необходимости держать виртуальное окружение на хосте.
- **CI/CD**: workflow `.github/workflows/runner-image.yml` повторно использует make-таргет на GitHub Actions,
  публикует артефакт в `ghcr.io/<org>/runner:<tag>` и подписывает образ через cosign (keyless, `COSIGN_EXPERIMENTAL=1`).
  Пайплайн требует `packages:write` и `id-token:write`, чтобы операторы могли тянуть подписанный production-ready билд
  без ручной сборки.
