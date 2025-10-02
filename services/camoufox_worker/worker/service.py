"""FastAPI application providing the Camoufox worker HTTP surface."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

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
    """Container storing shared application state objects."""

    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self.runner = RunnerClient(settings.runner_base_url)
        self.registry = CollectorRegistry()
        self.worker_id = str(uuid.uuid4())
        self.required_browser_flags = dict(settings.browser_required_flags)

    async def shutdown(self) -> None:
        """Release HTTP resources on shutdown."""

        await self.runner.close()


def get_settings() -> WorkerSettings:
    """Return cached worker settings for dependency injection."""

    return load_settings()


def create_app(settings: WorkerSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI worker application."""

    cfg = settings or load_settings()
    state = AppState(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.app_state = state
        try:
            yield
        finally:
            await state.shutdown()

    app = FastAPI(title="Camoufox Worker", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_state() -> AppState:
        return state

    @app.get("/health", response_model=HealthResponse)
    async def health(app_state: AppState = Depends(require_state)) -> HealthResponse:
        try:
            data = await app_state.runner.health()
            status_text = data.get("status", "unknown")
            checks = data.get("checks", {})
        except Exception as exc:  # pragma: no cover - defensive branch
            LOGGER.warning("runner health probe failed: %s", exc)
            status_text = "degraded"
            checks = {"runner": "unreachable"}
        return HealthResponse(status=status_text, version=app.version, checks=checks)

    @app.get("/sessions", response_model=list[SessionDetail])
    async def list_sessions(app_state: AppState = Depends(require_state)) -> list[SessionDetail]:
        data = await app_state.runner.list_sessions()
        return [_to_worker_detail(app_state, item) for item in data]

    @app.post("/sessions", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: SessionCreateRequest, app_state: AppState = Depends(require_state)
    ) -> SessionDetail:
        if request.vnc and not app_state.settings.supports_vnc:
            raise HTTPException(status_code=400, detail="VNC is not supported by this worker")

        payload = request.model_dump(exclude_unset=True)
        optional_flags = payload.pop("browser_flags", None)
        payload.setdefault("headless", app_state.settings.session_defaults.headless)
        payload.setdefault(
            "idle_ttl_seconds", app_state.settings.session_defaults.idle_ttl_seconds
        )
        payload.setdefault("start_url_wait", app_state.settings.session_defaults.start_url_wait)

        merged_flags = _merge_browser_flags(app_state.required_browser_flags, optional_flags)
        if merged_flags:
            metadata = payload.setdefault("metadata", {})
            metadata["browser_flags"] = merged_flags

        data = await app_state.runner.create_session(payload)
        return _to_worker_detail(app_state, data)

    @app.get("/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: str, app_state: AppState = Depends(require_state)) -> SessionDetail:
        try:
            data = await app_state.runner.get_session(session_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return _to_worker_detail(app_state, data)

    @app.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
    async def delete_session(
        session_id: str, app_state: AppState = Depends(require_state)
    ) -> SessionDeleteResponse:
        try:
            data = await app_state.runner.delete_session(session_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return SessionDeleteResponse(id=data["id"], status=SessionStatus(data["status"]))

    @app.post("/sessions/{session_id}/touch", response_model=SessionDetail)
    async def touch_session(
        session_id: str, app_state: AppState = Depends(require_state)
    ) -> SessionDetail:
        try:
            data = await app_state.runner.touch_session(session_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Session not found") from exc
            raise
        return _to_worker_detail(app_state, data)

    @app.get(cfg.metrics_endpoint)
    async def metrics(app_state: AppState = Depends(require_state)) -> Response:
        content = generate_latest(app_state.registry)
        return Response(content=content, media_type=CONTENT_TYPE_LATEST)

    @app.websocket("/sessions/{session_id}/ws")
    async def session_websocket(session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            state_ref: AppState = app.state.app_state
            data = await state_ref.runner.get_session(session_id)
        except httpx.HTTPStatusError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        upstream = data.get("ws_endpoint")
        if not upstream:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await _bridge_websocket(websocket, upstream)

    return app


def _merge_browser_flags(
    required: dict[str, Any], optional: dict[str, Any] | None
) -> dict[str, Any]:
    combined: dict[str, Any] = dict(optional or {})
    for key, value in required.items():
        combined[key] = value
    return combined


def _to_worker_detail(app_state: AppState, data: dict[str, Any]) -> SessionDetail:
    return SessionDetail(
        id=data["id"],
        status=SessionStatus(data["status"]),
        created_at=data["created_at"],
        last_seen_at=data["last_seen_at"],
        browser=data.get("browser", "camoufox"),
        headless=data["headless"],
        idle_ttl_seconds=data["idle_ttl_seconds"],
        labels=data.get("labels", {}),
        worker_id=app_state.worker_id,
        vnc_enabled=bool(data.get("vnc_enabled", False)),
        start_url_wait=data.get("start_url_wait", app_state.settings.session_defaults.start_url_wait),
        ws_endpoint=f"/sessions/{data['id']}/ws",
        vnc=data.get("vnc", {}) or {},
    )


async def _bridge_websocket(websocket: WebSocket, upstream_endpoint: str) -> None:
    try:
        async with websockets.connect(upstream_endpoint, ping_interval=None) as upstream:
            client_to_upstream = asyncio.create_task(
                _forward_client_to_upstream(websocket, upstream),
                name="camoufox-worker-client-to-runner",
            )
            upstream_to_client = asyncio.create_task(
                _forward_upstream_to_client(websocket, upstream),
                name="camoufox-worker-runner-to-client",
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
    except Exception as exc:  # pragma: no cover - defensive branch
        LOGGER.warning("websocket bridge failure: %s", exc)
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)


async def _forward_client_to_upstream(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
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
    try:
        async for payload in upstream:
            if isinstance(payload, (bytes, bytearray)):
                await websocket.send_bytes(payload)
            else:
                await websocket.send_text(payload)
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()


__all__ = ["create_app", "get_settings"]

