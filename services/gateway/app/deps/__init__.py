"""Dependency providers for the FastAPI routers."""

from __future__ import annotations

from core import AbstractSessionEventBridge
from fastapi import Request

from ..security import VncTokenService
from ..services.runner_registry import RunnerRegistry
from ..services.session_registry import SessionRegistry
from ..services.runner_client import RunnerControlClient


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


def get_runner_client(request: Request) -> RunnerControlClient:
    """Return the control-plane HTTP client used to reach runners."""

    return request.app.state.runner_client  # type: ignore[attr-defined]
