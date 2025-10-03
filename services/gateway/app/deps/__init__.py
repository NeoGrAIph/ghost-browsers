"""Dependency providers for FastAPI routers in the gateway service."""

from __future__ import annotations

from core import AbstractSessionEventBridge
from fastapi import Request, WebSocket

from ..security import VncTokenService
from ..services.runner_client import RunnerCommandClient
from ..services.runner_health import RunnerHealthClient
from ..services.runner_registry import RunnerRegistry
from ..services.runner_ws_proxy import RunnerWebSocketProxy
from ..services.session_registry import SessionRegistry
from ..services.workstation_registry import WorkstationRegistry


def get_session_registry(request: Request) -> SessionRegistry:
    """Return the session registry stored in the application state."""

    return request.app.state.session_registry  # type: ignore[attr-defined]


def get_runner_registry(request: Request) -> RunnerRegistry:
    """Return the runner registry stored in the application state."""

    return request.app.state.runner_registry  # type: ignore[attr-defined]


def get_event_bridge(request: Request) -> AbstractSessionEventBridge:
    """Return the event bridge shared across routers."""

    return request.app.state.event_bridge  # type: ignore[attr-defined]


def get_vnc_token_service(request: Request) -> VncTokenService:
    """Return the VNC token service stored on the application."""

    return request.app.state.vnc_tokens  # type: ignore[attr-defined]


def get_runner_command_client(request: Request) -> RunnerCommandClient:
    """Return the Runner command client shared by the application."""

    return request.app.state.runner_client  # type: ignore[attr-defined]


def get_runner_health_client(request: Request) -> RunnerHealthClient:
    """Return the Runner health client configured on the application."""

    return request.app.state.runner_health_client  # type: ignore[attr-defined]


def get_runner_ws_proxy(request: Request) -> RunnerWebSocketProxy:
    """Return the WebSocket proxy responsible for runner control tunnels."""

    return request.app.state.runner_ws_proxy  # type: ignore[attr-defined]


def get_workstation_registry(request: Request) -> WorkstationRegistry:
    """Return the workstation registry stored in the application state."""

    return request.app.state.workstation_registry  # type: ignore[attr-defined]


def get_session_registry_ws(websocket: WebSocket) -> SessionRegistry:
    """Return the session registry for WebSocket dependency injection."""

    return websocket.app.state.session_registry  # type: ignore[attr-defined]


def get_runner_registry_ws(websocket: WebSocket) -> RunnerRegistry:
    """Return the runner registry for WebSocket dependency injection."""

    return websocket.app.state.runner_registry  # type: ignore[attr-defined]


def get_runner_ws_proxy_ws(websocket: WebSocket) -> RunnerWebSocketProxy:
    """Return the WebSocket proxy when resolving dependencies on WS routes."""

    return websocket.app.state.runner_ws_proxy  # type: ignore[attr-defined]


__all__ = [
    "get_session_registry",
    "get_runner_registry",
    "get_event_bridge",
    "get_vnc_token_service",
    "get_runner_command_client",
    "get_runner_health_client",
    "get_runner_ws_proxy",
    "get_session_registry_ws",
    "get_runner_registry_ws",
    "get_runner_ws_proxy_ws",
    "get_workstation_registry",
]
