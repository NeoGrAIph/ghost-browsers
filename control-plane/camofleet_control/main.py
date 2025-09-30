"""FastAPI application that fronts multiple worker instances."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from .config import ControlSettings, WorkerConfig, load_settings
from .models import CreateSessionRequest, CreateSessionResponse, SessionDescriptor, WorkerStatus
from .service import worker_client

LOGGER = logging.getLogger(__name__)


class AppState:
    """Mutable state shared between request handlers."""

    def __init__(self, settings: ControlSettings) -> None:
        # Persist configuration so dependency functions can reuse it without
        # reloading environment variables.
        self.settings = settings
        # Round-robin index used by :meth:`pick_worker` to spread sessions
        # across the available workers.
        self._rr_index = 0

    def list_workers(self) -> list[WorkerConfig]:
        """Return a copy of the configured worker list."""

        return list(self.settings.workers)

    def pick_worker(
        self, preferred: str | None = None, *, require_vnc: bool = False
    ) -> WorkerConfig:
        """Select a worker by name or via round-robin balancing."""

        workers = [w for w in self.list_workers() if not require_vnc or w.supports_vnc]
        if preferred:
            for worker in workers:
                if worker.name == preferred:
                    return worker
            raise HTTPException(status_code=404, detail="Worker not found")
        if not workers:
            raise HTTPException(status_code=503, detail="No workers configured")
        worker = workers[self._rr_index % len(workers)]
        self._rr_index += 1
        return worker


def get_settings() -> ControlSettings:
    """Convenience dependency that loads the control-plane settings."""

    return load_settings()


def create_app(settings: ControlSettings | None = None) -> FastAPI:
    """Instantiate the FastAPI application used by the control plane."""

    cfg = settings or load_settings()
    app = FastAPI(title="Camofleet Control", version="0.1.0")
    # Relax CORS to allow the UI (which may run on another origin) to call the
    # API directly without running a separate proxy.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = AppState(cfg)

    def get_state() -> AppState:
        """Dependency returning the shared application state."""

        return state

    @app.get("/health")
    async def health(state: AppState = Depends(get_state)) -> dict:
        """Aggregate worker health into a single response."""

        worker_statuses = await gather_worker_status(state.list_workers(), cfg)
        healthy = all(item.healthy for item in worker_statuses) if worker_statuses else False
        return {"status": "ok" if healthy else "degraded", "workers": [s.model_dump() for s in worker_statuses]}

    @app.get("/workers", response_model=list[WorkerStatus])
    async def list_workers_endpoint(state: AppState = Depends(get_state)) -> list[WorkerStatus]:
        """Expose individual worker health data."""

        return await gather_worker_status(state.list_workers(), cfg)

    @app.get("/sessions", response_model=list[SessionDescriptor])
    async def list_sessions(state: AppState = Depends(get_state)) -> list[SessionDescriptor]:
        """Collect sessions from each worker and annotate them with public URLs."""

        results: list[SessionDescriptor] = []
        for worker in state.list_workers():
            async with worker_client(worker, cfg) as client:
                try:
                    response = await client.list_sessions()
                    response.raise_for_status()
                except httpx.HTTPError as exc:  # pragma: no cover - network failure
                    LOGGER.warning("Failed to query worker %s: %s", worker.name, exc)
                    continue
                for item in response.json():
                    public_ws_endpoint = build_public_ws_endpoint(cfg, worker.name, item["id"])
                    vnc_payload = apply_vnc_overrides(
                        worker,
                        item["id"],
                        item.get("vnc", item.get("vnc_info", {})),
                    )
                    vnc_enabled = item.get("vnc_enabled")
                    if vnc_enabled is None and vnc_payload:
                        vnc_enabled = bool(vnc_payload.get("http") or vnc_payload.get("ws"))
                    results.append(
                        SessionDescriptor(
                            worker=worker.name,
                            id=item["id"],
                            status=item["status"],
                            created_at=item["created_at"],
                            last_seen_at=item["last_seen_at"],
                            browser=item.get("browser", "camoufox"),
                            headless=item["headless"],
                            idle_ttl_seconds=item["idle_ttl_seconds"],
                            labels=item.get("labels", {}),
                            ws_endpoint=public_ws_endpoint,
                            vnc_enabled=vnc_enabled,
                            vnc=vnc_payload,
                            start_url_wait=item.get("start_url_wait"),
                        )
                    )
        return results

    @app.post("/sessions", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: CreateSessionRequest,
        state: AppState = Depends(get_state),
    ) -> CreateSessionResponse:
        """Request a new session from one of the configured workers."""

        worker = state.pick_worker(request.worker, require_vnc=request.vnc)
        payload = request.model_dump(exclude_unset=True)
        payload.pop("worker", None)
        async with worker_client(worker, cfg) as client:
            response = await client.create_session(payload)
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        body = response.json()
        body["ws_endpoint"] = build_public_ws_endpoint(cfg, worker.name, body["id"])
        body.setdefault("browser", "camoufox")
        if "vnc" not in body and "vnc_info" in body:
            body["vnc"] = body.pop("vnc_info")
        if "vnc" in body:
            body["vnc"] = apply_vnc_overrides(worker, body["id"], body["vnc"])
        if "vnc_enabled" not in body and "vnc" in body:
            body["vnc_enabled"] = bool(body["vnc"].get("http") or body["vnc"].get("ws"))
        return CreateSessionResponse(worker=worker.name, **body)

    @app.get("/sessions/{worker_name}/{session_id}", response_model=SessionDescriptor)
    async def get_session(
        worker_name: str, session_id: str, state: AppState = Depends(get_state)
    ) -> SessionDescriptor:
        """Return a single session descriptor from the selected worker."""

        worker = state.pick_worker(worker_name)
        async with worker_client(worker, cfg) as client:
            response = await client.get_session(session_id)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Session not found")
        response.raise_for_status()
        body = response.json()
        body["ws_endpoint"] = build_public_ws_endpoint(cfg, worker.name, body["id"])
        body.setdefault("browser", "camoufox")
        if "vnc" not in body and "vnc_info" in body:
            body["vnc"] = body.pop("vnc_info")
        if "vnc" in body:
            body["vnc"] = apply_vnc_overrides(worker, body["id"], body["vnc"])
        if "vnc_enabled" not in body and "vnc" in body:
            body["vnc_enabled"] = bool(body["vnc"].get("http") or body["vnc"].get("ws"))
        return SessionDescriptor(worker=worker.name, **body)

    @app.delete("/sessions/{worker_name}/{session_id}")
    async def delete_session(
        worker_name: str, session_id: str, state: AppState = Depends(get_state)
    ) -> dict:
        """Forward a session deletion request to a worker."""

        worker = state.pick_worker(worker_name)
        async with worker_client(worker, cfg) as client:
            response = await client.delete_session(session_id)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Session not found")
        response.raise_for_status()
        return response.json()

    @app.post("/sessions/{worker_name}/{session_id}/touch", response_model=SessionDescriptor)
    async def touch_session(
        worker_name: str,
        session_id: str,
        state: AppState = Depends(get_state),
    ) -> SessionDescriptor:
        """Refresh a session's idle timer via the underlying worker."""

        worker = state.pick_worker(worker_name)
        async with worker_client(worker, cfg) as client:
            response = await client.touch_session(session_id)
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Session not found")
        response.raise_for_status()
        body = response.json()
        body["ws_endpoint"] = build_public_ws_endpoint(cfg, worker.name, body["id"])
        body.setdefault("browser", "camoufox")
        if "vnc" not in body and "vnc_info" in body:
            body["vnc"] = body.pop("vnc_info")
        if "vnc" in body:
            body["vnc"] = apply_vnc_overrides(worker, body["id"], body["vnc"])
        if "vnc_enabled" not in body and "vnc" in body:
            body["vnc_enabled"] = bool(body["vnc"].get("http") or body["vnc"].get("ws"))
        return SessionDescriptor(worker=worker.name, **body)

    @app.websocket("/sessions/{worker_name}/{session_id}/ws")
    async def session_websocket(
        websocket: WebSocket,
        worker_name: str,
        session_id: str,
        state: AppState = Depends(get_state),
    ) -> None:
        """Proxy WebSocket traffic between the UI and the chosen worker."""

        worker = state.pick_worker(worker_name)
        upstream_endpoint = build_worker_ws_endpoint(worker, session_id)
        await websocket.accept()
        try:
            async with websockets.connect(
                upstream_endpoint,
                ping_interval=None,
                open_timeout=cfg.request_timeout,
            ) as upstream:
                client_to_upstream = asyncio.create_task(
                    _forward_client_to_upstream(websocket, upstream),
                    name="control-bridge-client->worker",
                )
                upstream_to_client = asyncio.create_task(
                    _forward_upstream_to_client(websocket, upstream),
                    name="control-bridge-worker->client",
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
            LOGGER.warning("WebSocket proxy failure for worker %s: %s", worker.name, exc)
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

    return app


async def gather_worker_status(workers: Iterable[WorkerConfig], cfg: ControlSettings) -> list[WorkerStatus]:
    """Fetch ``/health`` from every worker in parallel."""

    worker_list = list(workers)

    async def _fetch_status(worker: WorkerConfig) -> WorkerStatus:
        async with worker_client(worker, cfg) as client:
            try:
                response = await client.health()
                response.raise_for_status()
                detail = response.json()
                return WorkerStatus(
                    name=worker.name,
                    healthy=True,
                    detail=detail,
                    supports_vnc=worker.supports_vnc,
                )
            except httpx.HTTPError as exc:  # pragma: no cover
                LOGGER.warning("Worker %s unhealthy: %s", worker.name, exc)
                return WorkerStatus(
                    name=worker.name,
                    healthy=False,
                    detail={"error": str(exc)},
                    supports_vnc=worker.supports_vnc,
                )

    if not worker_list:
        return []

    return list(await asyncio.gather(*(_fetch_status(worker) for worker in worker_list)))


def apply_vnc_overrides(
    worker: WorkerConfig,
    session_id: str,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return VNC metadata with public overrides applied.

    Workers typically report loopback URLs (``http://127.0.0.1``) that are only
    meaningful from inside the cluster.  ``CONTROL_WORKERS`` allows operators to
    supply ingress-facing endpoints; this helper merges those values with the
    runner payload so API clients receive usable links.
    """

    source: Mapping[str, Any] = payload or {}
    if not source:
        return {}

    http_url = source.get("http")
    ws_url = source.get("ws")

    if not http_url and not ws_url:
        return {}

    result: dict[str, Any] = {**source}

    if http_url:
        result["http"] = _build_public_vnc_url(worker.vnc_http, session_id, http_url)
    else:
        result.pop("http", None)

    if ws_url:
        result["ws"] = _build_public_vnc_url(worker.vnc_ws, session_id, ws_url)
    else:
        result.pop("ws", None)

    return result


def _build_public_vnc_url(
    override_template: str | None,
    session_id: str,
    fallback: str | None,
) -> str | None:
    if not override_template:
        return fallback
    try:
        formatted = override_template.format(id=session_id)
    except Exception as exc:  # pragma: no cover - defensive against bad config
        LOGGER.warning("Invalid VNC override %s: %s", override_template, exc)
        return fallback
    try:
        override_parts = urlparse(formatted)
    except ValueError as exc:  # pragma: no cover - defensive against bad config
        LOGGER.warning("Failed to parse VNC override URL %s: %s", formatted, exc)
        return fallback

    fallback_parts = urlparse(fallback) if fallback else None

    scheme = override_parts.scheme or (fallback_parts.scheme if fallback_parts else "")
    netloc = override_parts.netloc or (fallback_parts.netloc if fallback_parts else "")
    path = _merge_vnc_paths(override_parts.path, fallback_parts.path if fallback_parts else "")

    query_items = parse_qsl(override_parts.query, keep_blank_values=True)
    seen = {key for key, _ in query_items}
    if fallback_parts and fallback_parts.query:
        for key, value in parse_qsl(fallback_parts.query, keep_blank_values=True):
            if key not in seen:
                query_items.append((key, value))
                seen.add(key)
    query = urlencode(query_items)

    return urlunparse((scheme, netloc, path or "/", "", query, ""))


def _merge_vnc_paths(override_path: str, fallback_path: str) -> str:
    original_override = override_path or ""
    base = original_override.rstrip("/")
    fallback = fallback_path or ""

    if not fallback or fallback == "/":
        return base or fallback or "/"

    base_segments = [segment for segment in base.split("/") if segment]
    fallback_segments = [segment for segment in fallback.split("/") if segment]

    if not base_segments:
        if not fallback_segments:
            return "/" if (original_override.startswith("/") or fallback.startswith("/")) else ""
        prefix = "/" if (original_override.startswith("/") or fallback.startswith("/")) else ""
        return f"{prefix}{'/'.join(fallback_segments)}"

    if fallback_segments and len(fallback_segments) >= len(base_segments):
        if fallback_segments[-len(base_segments):] == base_segments:
            leading_slash = original_override.startswith("/") or fallback.startswith("/")
            joined_base = "/".join(base_segments)
            return f"/{joined_base}" if leading_slash else joined_base

    common = 0
    limit = min(len(base_segments), len(fallback_segments))
    while common < limit and base_segments[common] == fallback_segments[common]:
        common += 1

    merged_segments = base_segments + fallback_segments[common:]

    if not merged_segments:
        return "/"

    leading_slash = original_override.startswith("/") or fallback.startswith("/")
    joined = "/".join(merged_segments)
    return f"/{joined}" if leading_slash else joined


def build_public_ws_endpoint(settings: ControlSettings, worker_name: str, session_id: str) -> str:
    """Construct the public WebSocket path exposed by the control plane."""

    prefix = normalise_public_prefix(settings.public_api_prefix)
    return f"{prefix}/sessions/{worker_name}/{session_id}/ws"


def build_worker_ws_endpoint(worker: WorkerConfig, session_id: str) -> str:
    """Translate the worker HTTP endpoint into a WebSocket URL."""

    parsed = urlparse(worker.url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    if path:
        path = f"{path}/sessions/{session_id}/ws"
    else:
        path = f"/sessions/{session_id}/ws"
    base = parsed._replace(scheme=scheme, path=path, params="", query="", fragment="")
    return urlunparse(base)


def normalise_public_prefix(prefix: str) -> str:
    """Ensure the configured prefix is safe to concatenate with paths."""

    value = (prefix or "").strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/")


async def _forward_client_to_upstream(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
    """Relay messages arriving from the public client to the worker."""

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
    """Relay messages originating from the worker to the public client."""

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
