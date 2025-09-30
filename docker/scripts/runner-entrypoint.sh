#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  if [ -n "${VNC_PID:-}" ]; then
    kill "$VNC_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

normalize_bool() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if normalize_bool "${RUNNER_DISABLE_HTTP3:-}"; then
  export MOZ_DISABLE_HTTP3=1
  export MOZ_DISABLE_QUIC=1
fi

if [ "${RUNNER_VNC_LEGACY:-0}" = "1" ]; then
  /usr/local/bin/vnc-start.sh &
  VNC_PID=$!
fi

exec python -m camoufox_runner
