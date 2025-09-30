"""FastAPI application that exposes the Camoufox runner API."""

from __future__ import annotations

import asyncio
import logging

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from .config import RunnerSettings, load_settings
from .models import (
    HealthResponse,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionDetail,
)
from .sessions import SessionManager, VNCUnavailableError

LOGGER = logging.getLogger(__name__)


class AppState:
    """Shared mutable objects required by the FastAPI application."""

    def __init__(self, settings: RunnerSettings) -> None:
        # Configuration values derived from the environment.
        self.settings = settings
        # ``SessionManager`` is created lazily during startup once Playwright is
        # ready.
        self.manager: SessionManager | None = None
        # Metrics registry exported at ``/metrics``.
        self.registry = CollectorRegistry()
        # Store the Playwright object so we can stop it during shutdown.
        self._playwright = None

    async def startup(self) -> None:
        """Initialise Playwright and the session manager."""

        LOGGER.info("Starting Camoufox runner")
        self._playwright = await async_playwright().start()
        manager = SessionManager(self.settings, self._playwright)
        await manager.start()
        self.manager = manager

    async def shutdown(self) -> None:
        """Gracefully shut down the session manager and Playwright."""

        LOGGER.info("Shutting down Camoufox runner")
        if self.manager:
            await self.manager.close()
        if self._playwright:
            await self._playwright.stop()


def get_settings() -> RunnerSettings:
    """Convenience dependency for loading runner settings."""

    return load_settings()


def create_app(settings: RunnerSettings | None = None) -> FastAPI:
    """Create the FastAPI application that controls Playwright sessions."""

    cfg = settings or load_settings()
    app = FastAPI(title="Camoufox Runner", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = AppState(cfg)
    app.state.app_state = state

    @app.on_event("startup")
    async def _startup() -> None:
        """Initialise background services when the application boots."""

        await state.startup()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        """Tear down resources once the server stops."""

        await state.shutdown()

    def get_manager() -> SessionManager:
        """Dependency that returns the active :class:`SessionManager`."""

        if not state.manager:
            raise HTTPException(status_code=503, detail="Runner initialising")
        return state.manager

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Simple endpoint used for readiness checks."""

        checks = {"playwright": "ok" if state.manager else "starting"}
        return HealthResponse(status="ok", version=app.version, checks=checks)

    @app.get("/sessions", response_model=list[SessionDetail])
    async def list_sessions(manager: SessionManager = Depends(get_manager)) -> list[SessionDetail]:
        """List all active sessions managed by the runner."""

        return await manager.list_details()

    @app.post("/sessions", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: SessionCreateRequest,
        manager: SessionManager = Depends(get_manager),
    ) -> SessionDetail:
        """Create a new session, respecting optional VNC constraints."""

        payload = request.model_dump(exclude_unset=True)
        try:
            handle = await manager.create(payload)
        except VNCUnavailableError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return manager.detail_for(handle)

    @app.get("/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(
        session_id: str, manager: SessionManager = Depends(get_manager)
    ) -> SessionDetail:
        """Retrieve an existing session by identifier."""

        handle = await manager.get(session_id)
        if not handle:
            raise HTTPException(status_code=404, detail="Session not found")
        return manager.detail_for(handle)

    @app.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
    async def delete_session(
        session_id: str,
        manager: SessionManager = Depends(get_manager),
    ) -> SessionDeleteResponse:
        """Terminate a session and return the final state."""

        handle = await manager.delete(session_id)
        if not handle:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionDeleteResponse(id=handle.id, status=handle.status)

    @app.post("/sessions/{session_id}/touch", response_model=SessionDetail)
    async def touch_session(
        session_id: str,
        manager: SessionManager = Depends(get_manager),
    ) -> SessionDetail:
        """Refresh a session's idle timeout and return its detail payload."""

        handle = await manager.touch(session_id)
        if not handle:
            raise HTTPException(status_code=404, detail="Session not found")
        return handle.detail(manager.ws_endpoint_for(handle), manager._build_vnc_payload(handle))

    @app.get(cfg.metrics_endpoint)
    async def metrics() -> Response:
        """Expose Prometheus metrics about the runner internals."""

        data = generate_latest(state.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()


__all__ = ["create_app", "app"]
