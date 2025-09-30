#!/usr/bin/env bash
set -euo pipefail

: "${DISPLAY:=:1}"
: "${VNC_RES:=1920x1080x24}"
: "${VNC_PORT:=5900}"
: "${WS_PORT:=6900}"
: "${VNC_PASSWORD:=}"

Xvfb "$DISPLAY" -screen 0 "$VNC_RES" +extension RANDR -nolisten tcp &
XVFB_PID=$!

cleanup() {
  kill "$XVFB_PID" >/dev/null 2>&1 || true
  kill "$X11VNC_PID" >/dev/null 2>&1 || true
  kill "$WEBSOCKIFY_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sleep 0.5

if [ -n "$VNC_PASSWORD" ]; then
  PASSFILE="/tmp/vncpass"
  x11vnc -storepasswd "$VNC_PASSWORD" "$PASSFILE" >/dev/null
  AUTH="-rfbauth $PASSFILE"
else
  AUTH="-nopw"
fi

x11vnc -display "$DISPLAY" -shared -forever -rfbport "$VNC_PORT" $AUTH -quiet &
X11VNC_PID=$!

if command -v websockify >/dev/null 2>&1; then
  if [ -d /usr/share/novnc ]; then
    websockify --web=/usr/share/novnc/ "$WS_PORT" localhost:"$VNC_PORT" &
  else
    websockify "$WS_PORT" localhost:"$VNC_PORT" &
  fi
  WEBSOCKIFY_PID=$!
else
  WEBSOCKIFY_PID=0
fi

echo "[VNC] DISPLAY=$DISPLAY VNC_PORT=$VNC_PORT WS_PORT=$WS_PORT"
wait "$X11VNC_PID"
