# Camofleet k3s deployment

These manifests provide a minimal deployment ready for a k3s cluster:

- `worker` — API-под с sidecar runner'ом (Camoufox) в headless режиме.
- `worker-vnc` — такая же пара контейнеров, но runner собран с VNC/noVNC.
- `vnc-gateway` — сервис, который проксирует noVNC/ws трафик через фиксированный порт.
- `control-plane` — lightweight orchestrator that proxies API requests to workers.
- `ui` — static React dashboard served by nginx.

## Prerequisites

1. Build and push the container images. Replace the registry references in the manifests.
   ```sh
   docker build -t REGISTRY/camofleet-runner:latest -f docker/Dockerfile.runner .
   docker build -t REGISTRY/camofleet-runner-vnc:latest -f docker/Dockerfile.runner-vnc .
   docker build -t REGISTRY/camofleet-worker:latest -f docker/Dockerfile.worker .
   docker build -t REGISTRY/camofleet-control:latest -f docker/Dockerfile.control .
   docker build -t REGISTRY/camofleet-vnc-gateway:latest -f docker/Dockerfile.vnc-gateway .
   docker build -t REGISTRY/camofleet-ui:latest -f docker/Dockerfile.ui .
   docker push REGISTRY/camofleet-runner:latest
   docker push REGISTRY/camofleet-runner-vnc:latest
   docker push REGISTRY/camofleet-worker:latest
   docker push REGISTRY/camofleet-control:latest
   docker push REGISTRY/camofleet-vnc-gateway:latest
   docker push REGISTRY/camofleet-ui:latest
   ```
2. Configure an Ingress controller in the cluster (e.g. Traefik, NGINX).
3. Provision a PersistentVolume if you need to keep session artefacts between restarts.

## Deploy

Update the image references inside `kustomization.yaml`, then apply:

```sh
kubectl apply -k deploy/k8s
```

This creates deployments for headless и VNC воркеров (каждый — пара контейнеров worker+runner),
шлюз VNC, контрольную плоскость, UI и Ingress. VNC gateway выступает единым входом (`/vnc`),
поэтому наружу больше не требуется проксировать весь диапазон портов 6900–6999 — сервис держит
фиксированный порт 6080 и самостоятельно подключается к нужному runner-у внутри кластера.

## Environment variables

### Worker + runner

- `WORKER_RUNNER_BASE_URL` — адрес sidecar runner'а (по умолчанию `http://localhost:8070`).
- `WORKER_SUPPORTS_VNC` — флаг, который сигнализирует control-plane, что воркер умеет в VNC.
- `RUNNER_VNC_WS_BASE` / `RUNNER_VNC_HTTP_BASE` — задаются только для runner-vnc и используются UI.
- `RUNNER_DISABLE_HTTP3` / `MOZ_DISABLE_HTTP3` — отключают HTTP/3 и Alt-Svc апгрейды в Firefox, чтобы запросы шли по TCP (HTTP/2/1.1).
- `RUNNER_DISABLE_WEBRTC` — запрещает WebRTC, исключая любые UDP-попытки из браузера внутри кластера.

### Control-plane

The control-plane reads workers from `CONTROL_WORKERS`, a JSON array of worker objects. The
manifest sets this automatically using the `CONTROL_WORKERS` environment variable.

Example value:

```json
[
  {
    "name": "worker-headless",
    "url": "http://camofleet-worker:8080",
    "supports_vnc": false
  },
  {
    "name": "worker-vnc",
    "url": "http://camofleet-worker-vnc:8080",
    "supports_vnc": true,
    "vnc_ws": "wss://camofleet.local/websockify?token={id}",
    "vnc_http": "https://camofleet.local/vnc/{id}"
  }
]
```
Runner автоматически подменяет порт в этих базовых URL на выделенный для конкретной VNC-сессии.
Замените `camofleet.local` на реальный хост, под которым публикуется Ingress.

### VNC gateway

The gateway принимает HTTP и WebSocket запросы под префиксом `/vnc` (Traefik добавляет его автоматически;
при необходимости можно изменить конфигурацией Ingress) и перенаправляет их на runner. Основные
переменные окружения:

- `VNCGATEWAY_RUNNER_HOST` — DNS-имя сервиса с runner-vnc (по умолчанию `camofleet-worker-vnc`).
- `VNCGATEWAY_MIN_PORT` / `VNCGATEWAY_MAX_PORT` — диапазон websockify-портов, который выделяет runner.

### UI

By default the UI expects the control-plane at `/api`. Adjust the nginx configuration if you
expose it differently.

## TLS

The sample Ingress references a TLS secret named `camofleet-tls`. Provide your own certificate
or remove the TLS section for HTTP-only testing.
