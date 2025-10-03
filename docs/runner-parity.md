# Runner Parity Notes

## Implemented Concepts

- **FastAPI lifecycle wiring** – The runner starts and stops its session manager
  using FastAPI startup/shutdown hooks so that the idle reaper and warm pool are
  always initialised and torn down with the application lifecycle.
- **Validated configuration surface** – `RunnerSettings` centralises environment
  parsing, validates VNC ranges, and exposes toggles for warm pool, proxies, and
  prewarm navigation.
- **Hybrid warm pool acquisition** – `SessionManager` prefers prewarmed
  workstations when available, falls back to cold launches when configured, and
  propagates warm-pool metadata to session records.
- **Process-backed VNC orchestration** – `ProcessVncController` manages a bounded
  pool of displays/ports and spawns Xvfb, x11vnc, and websockify to expose HTTP
  and WebSocket endpoints.
- **Prewarm navigation with TTL tracking** – `WarmPoolManager` optionally
  navigates to the configured start URL, waits for stabilisation, and records
  statistics surfaced via the health endpoint alongside idle reaper metrics.
- **Sanitised VNC payloads** – Session metadata drops user-provided VNC tokens
  so that credential issuance remains delegated to the gateway.

## Recent parity improvements

- Browser network hardening flags supplied by the worker (for example
  disabling HTTP/3/Alt-Svc via `MOZ_DISABLE_HTTP3`) are now honoured during cold
  launches and warm pool provisioning through `RunnerSettings.browser_required_flags`.
- Docker image now includes locale generation, Windows-compatible fonts, and
  VNC helper binaries (Xvfb/x11vnc/websockify/noVNC) so that headless and VNC
  workflows match the beta "thick" build while retaining cached dependency
  layers.
