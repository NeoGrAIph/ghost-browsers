"""Application factory for the Camou Gateway service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import anyio
from core import InMemorySessionEventBridge, Runner
from fastapi import FastAPI

from .config import GatewaySettings
from .routers import events_router, runners_router, sessions_router, workstations_router
from .security import KeycloakAuthenticator, VncTokenService
from .services.discovery import (
    RunnerDiscoveryService,
    purge_sessions_for_missing_runners,
)
from .services.runner_client import RunnerCommandClient, RunnerCommandError
from .services.runner_health import RunnerHealthClient
from .services.runner_registry import RunnerRegistry
from .services.runner_ws_proxy import RunnerWebSocketProxy
from .services.session_registry import SessionRegistry
from .services.workstation_registry import WorkstationRegistry

_LOGGER = logging.getLogger(__name__)


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""

    config = settings or GatewaySettings.from_env()
    app = FastAPI(title="Camou Gateway", version="0.1.0")
    app.state.settings = config
    app.state.session_registry = SessionRegistry()
    app.state.runner_registry = RunnerRegistry(config.runners)
    app.state.event_bridge = InMemorySessionEventBridge()
    app.state.vnc_tokens = VncTokenService(
        secret=config.vnc_token_secret,
        ttl_seconds=config.vnc_token_ttl_seconds,
    )
    app.state.authenticator = KeycloakAuthenticator(config.jwt_jwks_url)
    app.state.runner_client = RunnerCommandClient()
    app.state.runner_health_client = RunnerHealthClient()
    app.state.runner_ws_proxy = RunnerWebSocketProxy()
    app.state.workstation_registry = WorkstationRegistry()
    app.state.runner_discovery = RunnerDiscoveryService(
        settings=config,
        runner_registry=app.state.runner_registry,
        session_registry=app.state.session_registry,
    )

    app.include_router(sessions_router)
    app.include_router(runners_router)
    app.include_router(events_router)
    app.include_router(workstations_router)

    _LOGGER.debug(
        "Gateway application initialised",
        extra={"discovery_mode": config.discovery_mode},
    )
    app.router.lifespan_context = _lifespan(app)
    return app


def _lifespan(app: FastAPI):
    """Create the FastAPI lifespan context managing background tasks."""

    @asynccontextmanager
    async def _context(_: FastAPI):
        discovery: RunnerDiscoveryService = app.state.runner_discovery
        registry: RunnerRegistry = app.state.runner_registry
        session_registry: SessionRegistry = app.state.session_registry
        initial = await discovery.refresh()
        await purge_sessions_for_missing_runners(
            session_registry,
            registry,
            initial.removed,
        )
        runners = await registry.list()
        await _restore_runner_sessions(app, runners)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(_runner_maintenance_loop, app)
            try:
                yield
            finally:  # pragma: no cover - cancellation path
                task_group.cancel_scope.cancel()

    return _context


async def _restore_runner_sessions(app: FastAPI, runners: list[Runner]) -> None:
    """Repopulate session registries from healthy runner snapshots.

    Args:
        app: FastAPI application exposing stateful registries and clients.
        runners: Collection of runners observed during discovery.

    Returns:
        None. The coroutine updates the in-memory registries in place.

    Example:
        >>> await _restore_runner_sessions(app, await registry.list())  # doctest: +SKIP
    """

    if not runners:
        return

    session_registry: SessionRegistry = app.state.session_registry
    runner_registry: RunnerRegistry = app.state.runner_registry
    runner_client: RunnerCommandClient = app.state.runner_client

    restored = 0
    for runner in runners:
        if not runner.healthy:
            continue
        try:
            sessions = await runner_client.list_sessions(runner)
        except RunnerCommandError as exc:
            _LOGGER.warning(
                "Failed to recover sessions from runner %s: %s",
                runner.id,
                exc,
            )
            continue

        for session in sessions:
            if session.runner_id and session.runner_id != runner.id:
                _LOGGER.warning(
                    "Skipping session %s reported by runner %s due to mismatched owner %s",
                    session.id,
                    runner.id,
                    session.runner_id,
                )
                continue
            await session_registry.upsert(session)
            await runner_registry.register_session_ws_endpoint(
                session.id,
                runner_id=runner.id,
                target=session.ws_endpoint,
            )
            restored += 1

    if restored:
        _LOGGER.info("Recovered %s session(s) from healthy runners", restored)


async def _runner_maintenance_loop(app: FastAPI) -> None:
    """Background loop polling runners and cleaning stale sessions."""

    settings: GatewaySettings = app.state.settings
    registry: RunnerRegistry = app.state.runner_registry
    session_registry: SessionRegistry = app.state.session_registry
    health_client: RunnerHealthClient = app.state.runner_health_client
    discovery: RunnerDiscoveryService = app.state.runner_discovery
    interval = max(settings.discovery_poll_interval_seconds, 0.1)

    while True:
        try:
            result = await discovery.refresh()
            runners = await registry.list()
            for runner in runners:
                await health_client.probe(runner, registry)
            await purge_sessions_for_missing_runners(
                session_registry,
                registry,
                result.removed,
            )
        except Exception:  # pragma: no cover - defensive logging
            _LOGGER.exception("Runner maintenance iteration failed")
        await anyio.sleep(interval)
