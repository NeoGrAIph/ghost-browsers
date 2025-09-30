"""Worker service that proxies requests to the Camoufox runner sidecar."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from .config import WorkerSettings, load_settings
from .models import (
    HealthResponse,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionDetail,
    SessionStatus,
)
from .runner_client import RunnerClient

LOGGER = logging.getLogger(__name__)


class AppState:
    """Container for objects shared across FastAPI dependency scopes.

    FastAPI encourages keeping global state to a minimum.  Instead of scattering
    singletons around the module we store everything that must outlive a single
    request inside :class:`AppState`.  The instance is attached to ``app.state``
    which allows dependency functions to access the runner client, metrics
    registry and the generated worker identifier.
    """

    def __init__(self, settings: WorkerSettings) -> None:
        # Persist the resolved application settings so handlers can reference
        # feature flags (for example, whether this worker supports VNC).
        self.settings = settings
        # ``RunnerClient`` is a thin async HTTP client responsible for talking
        # to the sidecar that manages real browser sessions.
        self.runner = RunnerClient(settings.runner_base_url)
        # ``CollectorRegistry`` stores Prometheus metrics that we expose from
        # the ``/metrics`` endpoint.
        self.registry = CollectorRegistry()
        # Give each worker a unique identifier so callers can see which
        # instance handled a request without relying on infrastructure details.
        self.worker_id = str(uuid.uuid4())

    async def shutdown(self) -> None:
        """Release network resources when FastAPI shuts down."""

        await self.runner.close()


def get_settings() -> WorkerSettings:
    """Convenience dependency that loads the configuration."""

    return load_settings()


def create_app(settings: WorkerSettings | None = None) -> FastAPI:
    """Create a configured FastAPI instance.

    The worker can be started both through ``uvicorn`` and unit tests.  Allowing
    an optional ``settings`` argument enables tests to inject a fully controlled
    configuration while regular bootstrapping continues to read from the
    environment.
    """

    cfg = settings or load_settings()
    app = FastAPI(title="Camofleet Worker", version="0.2.0")
    # Relax CORS restrictions because the public UI and third-party tools may
    # run on different origins.  All security is enforced at the infrastructure
    # level (private networks, authentication proxies, etc.).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialise the shared state container and attach it to ``app.state`` so
    # dependencies can discover it without relying on global variables.
    state = AppState(cfg)
    app.state.app_state = state

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        """Ensure the runner HTTP client is closed during graceful shutdown."""

        await state.shutdown()

    def require_state() -> AppState:
        """FastAPI dependency that returns the shared application state."""

        return state

    @app.get("/health", response_model=HealthResponse)
    async def health(app_state: AppState = Depends(require_state)) -> HealthResponse:
        """Proxy the runner health check and normalise the response."""

        try:
            runner_health = await app_state.runner.health()
            status_text = runner_health.get("status", "unknown")
            checks = runner_health.get("checks", {})
        except Exception as exc:  # pragma: no cover - defensive path
            # A failure to reach the runner should not explode the endpoint —
            # callers only need to know that something is degraded.
            LOGGER.warning("Runner health check failed: %s", exc)
            status_text = "degraded"
            checks = {"runner": "unreachable"}
        return HealthResponse(
            status=status_text,
            version=app.version,
            checks=checks,
        )

    @app.get("/sessions", response_model=list[SessionDetail])
    async def list_sessions(app_state: AppState = Depends(require_state)) -> list[SessionDetail]:
        """Return all sessions reported by the runner service."""

        data = await app_state.runner.list_sessions()
        return [_to_worker_detail(app_state, item) for item in data]

    @app.post("/sessions", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: SessionCreateRequest,
        app_state: AppState = Depends(require_state),
    ) -> SessionDetail:
        """Create a new browser session through the runner sidecar."""

        if request.vnc and not app_state.settings.supports_vnc:
            raise HTTPException(status_code=400, detail="VNC is not supported by this worker")
        # ``model_dump(exclude_unset=True)`` keeps the payload tidy by omitting
        # optional fields that the client did not specify.
        payload = request.model_dump(exclude_unset=True)
        # Respect defaults defined in configuration when the client left a
        # field blank.
        payload.setdefault("headless", app_state.settings.session_defaults.headless)
        payload.setdefault("idle_ttl_seconds", app_state.settings.session_defaults.idle_ttl_seconds)
        data = await app_state.runner.create_session(payload)
        return _to_worker_detail(app_state, data)

    @app.get("/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: str, app_state: AppState = Depends(require_state)) -> SessionDetail:
        """Return information about a specific session."""

        try:
            data = await app_state.runner.get_session(session_id)
        except httpx.HTTPStatusError as exc:
            # Convert the runner's 404 error into a FastAPI HTTPException so the
            # client receives the expected response body.
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return _to_worker_detail(app_state, data)

    @app.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
    async def delete_session(session_id: str, app_state: AppState = Depends(require_state)) -> SessionDeleteResponse:
        """Request graceful termination of a session."""

        try:
            data = await app_state.runner.delete_session(session_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return SessionDeleteResponse(id=data["id"], status=SessionStatus(data["status"]))

    @app.post("/sessions/{session_id}/touch", response_model=SessionDetail)
    async def touch_session(session_id: str, app_state: AppState = Depends(require_state)) -> SessionDetail:
        """Refresh the session's idle timeout."""

        try:
            data = await app_state.runner.touch_session(session_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return _to_worker_detail(app_state, data)

    @app.get(cfg.metrics_endpoint)
    async def metrics(app_state: AppState = Depends(require_state)) -> Response:
        """Expose collected Prometheus metrics."""

        data = generate_latest(app_state.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @app.websocket("/sessions/{session_id}/ws")
    async def session_websocket(session_id: str, websocket: WebSocket) -> None:
        """Bidirectionally proxy WebSocket traffic between the client and runner."""

        await websocket.accept()
        try:
            data = await state.runner.get_session(session_id)
        except httpx.HTTPStatusError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        upstream_endpoint = data.get("ws_endpoint")
        if not upstream_endpoint:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await _bridge_websocket(websocket, upstream_endpoint)

    return app


def _to_worker_detail(app_state: AppState, data: dict) -> SessionDetail:
    """Normalize runner payloads to the schema expected by the API clients."""

    return SessionDetail(
        id=data["id"],
        status=SessionStatus(data["status"]),
        created_at=data["created_at"],
        last_seen_at=data["last_seen_at"],
        browser="camoufox",
        headless=data["headless"],
        idle_ttl_seconds=data["idle_ttl_seconds"],
        labels=data.get("labels", {}),
        worker_id=app_state.worker_id,
        vnc_enabled=data.get("vnc", False),
        start_url_wait=data.get("start_url_wait", "load"),
        # For clients the worker's WebSocket endpoint is always relative to the
        # API base URL; constructing it here saves them from guessing.
        ws_endpoint=f"/sessions/{data['id']}/ws",
        vnc=data.get("vnc_info", {}),
    )


async def _bridge_websocket(websocket: WebSocket, upstream_endpoint: str) -> None:
    """Pipe messages in both directions between the client and the runner."""

    try:
        async with websockets.connect(upstream_endpoint, ping_interval=None) as upstream:
            client_to_upstream = asyncio.create_task(
                _forward_client_to_upstream(websocket, upstream),
                name="camoufox-bridge-client->upstream",
            )
            upstream_to_client = asyncio.create_task(
                _forward_upstream_to_client(websocket, upstream),
                name="camoufox-bridge-upstream->client",
            )
            done, pending = await asyncio.wait(
                {client_to_upstream, upstream_to_client},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
    except (ConnectionClosedError, ConnectionClosedOK, WebSocketDisconnect):
        with contextlib.suppress(RuntimeError):
            await websocket.close()
    except Exception as exc:  # pragma: no cover - defensive logging path
        LOGGER.warning("WebSocket bridge failure: %s", exc)
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def _forward_client_to_upstream(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
    """Relay messages received from the UI to the runner WebSocket."""

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                await upstream.close()
                break
            if "text" in message and message["text"] is not None:
                await upstream.send(message["text"])
            elif "bytes" in message and message["bytes"] is not None:
                await upstream.send(message["bytes"])
    except WebSocketDisconnect:
        await upstream.close()


async def _forward_upstream_to_client(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
    """Relay messages originating from the runner to the UI."""

    try:
        async for data in upstream:
            if isinstance(data, (bytes, bytearray)):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()


__all__ = ["create_app"]
