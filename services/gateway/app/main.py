"""Application factory for the Camou Gateway service."""

from __future__ import annotations

import logging

from core import InMemorySessionEventBridge
from fastapi import FastAPI

from .config import GatewaySettings
from .routers import events_router, runners_router, sessions_router
from .security import KeycloakAuthenticator, VncTokenService
from .services.runner_registry import RunnerRegistry
from .services.session_registry import SessionRegistry

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

    app.include_router(sessions_router)
    app.include_router(runners_router)
    app.include_router(events_router)

    _LOGGER.debug(
        "Gateway application initialised",
        extra={"discovery_mode": config.discovery_mode},
    )
    return app
