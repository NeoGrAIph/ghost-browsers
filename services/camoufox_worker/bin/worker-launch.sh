#!/usr/bin/env bash
set -euo pipefail

# Allow overriding the underlying CLI invocation by passing explicit arguments.
if [[ $# -gt 0 ]]; then
  exec python -m worker.main "$@"
fi

if [[ -z "${WORKER_JOB_URL:-}" ]]; then
  cat <<'USAGE' >&2
worker-launch: expected WORKER_JOB_URL to be set or CLI arguments to be supplied.

Environment variables:
  WORKER_JOB_URL          — обязательный URL для выполнения задачи.
  WORKER_MODE             — режим запуска (native/orchestrator). По умолчанию: native.
  WORKER_TIMEOUT          — таймаут выполнения (сек). По умолчанию: 60.
  WORKER_POLL_TIMEOUT     — таймаут ожидания orchestrator-сессии (сек). По умолчанию: 90.
  WORKER_POLL_INTERVAL    — интервал опроса orchestrator-сессии (сек). По умолчанию: 1.
  WORKER_GATEWAY_URL      — алиас для GATEWAY_URL (обязателен в orchestrator-режиме).
  WORKER_GATEWAY_TOKEN    — алиас для GATEWAY_TOKEN (обязателен в orchestrator-режиме).
  WORKER_EXTRA_ARGS       — дополнительные флаги CLI (строка, разделённая пробелами).

Пример:
  docker run --rm \
    -e WORKER_JOB_URL=https://example.com \
    -e WORKER_MODE=native \
    ghcr.io/org/camoufox-worker:latest
USAGE
  exit 64
fi

mode="${WORKER_MODE:-native}"
if [[ "${mode}" != "native" && "${mode}" != "orchestrator" ]]; then
  echo "worker-launch: unsupported WORKER_MODE '${mode}'. Use native or orchestrator." >&2
  exit 64
fi

timeout="${WORKER_TIMEOUT:-60}"
poll_timeout="${WORKER_POLL_TIMEOUT:-90}"
poll_interval="${WORKER_POLL_INTERVAL:-1}"

gateway_url="${WORKER_GATEWAY_URL:-${GATEWAY_URL:-}}"
gateway_token="${WORKER_GATEWAY_TOKEN:-${GATEWAY_TOKEN:-}}"

if [[ "${mode}" == "orchestrator" ]]; then
  if [[ -z "${gateway_url}" ]]; then
    echo "worker-launch: orchestrator mode requires WORKER_GATEWAY_URL or GATEWAY_URL." >&2
    exit 64
  fi
  if [[ -z "${gateway_token}" ]]; then
    echo "worker-launch: orchestrator mode requires WORKER_GATEWAY_TOKEN or GATEWAY_TOKEN." >&2
    exit 64
  fi
fi

if [[ -n "${gateway_url}" ]]; then
  export GATEWAY_URL="${gateway_url}"
fi
if [[ -n "${gateway_token}" ]]; then
  export GATEWAY_TOKEN="${gateway_token}"
fi

read -r -a extra_args <<< "${WORKER_EXTRA_ARGS:-}"

cmd=(
  python -m worker.main run
  --url "${WORKER_JOB_URL}"
  --mode "${mode}"
  --timeout "${timeout}"
  --poll-timeout "${poll_timeout}"
  --poll-interval "${poll_interval}"
)

if ((${#extra_args[@]} > 0)); then
  exec "${cmd[@]}" "${extra_args[@]}"
else
  exec "${cmd[@]}"
fi
