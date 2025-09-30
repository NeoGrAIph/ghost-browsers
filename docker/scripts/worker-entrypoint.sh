#!/usr/bin/env bash
set -euo pipefail

/usr/local/bin/vnc-start.sh &
VNC_PID=$!

cleanup() {
  kill "$VNC_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

exec python -m camofleet_worker
