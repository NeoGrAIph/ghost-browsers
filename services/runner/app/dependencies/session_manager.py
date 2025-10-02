"""Dependency wiring for session management and event publishers."""

from __future__ import annotations

import logging
from functools import lru_cache

from ..config import RunnerSettings
from ..events import (
    HttpSessionEventPublisher,
    InMemorySessionEventPublisher,
    SessionEventPublisher,
)
from ..session_manager import SessionManager
from ..vnc import ProcessVncController, VncController, VncUnavailableError
from ..warm_pool import WarmPoolManager
from ..workstation_events import (
    HttpWorkstationEventPublisher,
    InMemoryWorkstationEventPublisher,
    WorkstationEventPublisher,
)

LOGGER = logging.getLogger(__name__)


@lru_cache
def get_runner_settings() -> RunnerSettings:
    """Return cached :class:`RunnerSettings` parsed from the environment."""

    return RunnerSettings.from_env()


@lru_cache
def get_event_publisher() -> SessionEventPublisher:
    """Return the configured session event publisher based on settings."""

    settings = get_runner_settings()
    if settings.event_endpoint is not None:
        return HttpSessionEventPublisher(str(settings.event_endpoint))
    return InMemorySessionEventPublisher()


@lru_cache
def get_workstation_event_publisher() -> WorkstationEventPublisher:
    """Return the workstation event publisher configured for the runner."""

    settings = get_runner_settings()
    if settings.workstation_event_endpoint is not None:
        return HttpWorkstationEventPublisher(str(settings.workstation_event_endpoint))
    return InMemoryWorkstationEventPublisher()


@lru_cache
def get_vnc_controller() -> VncController | None:
    """Instantiate the process-based VNC controller when tooling is available."""

    settings = get_runner_settings()
    if not settings.vnc_enabled:
        return None
    try:
        return ProcessVncController(settings)
    except VncUnavailableError as exc:
        LOGGER.warning("VNC disabled: %s", exc)
        return None


@lru_cache
def get_session_manager() -> SessionManager:
    """Return a singleton :class:`SessionManager` wired with default dependencies."""

    return SessionManager(
        get_runner_settings(),
        get_event_publisher(),
        vnc_controller=get_vnc_controller(),
        warm_pool_manager=get_warm_pool_manager(),
    )


@lru_cache
def get_warm_pool_manager() -> WarmPoolManager:
    """Return a cached :class:`WarmPoolManager` built from runner settings."""

    return WarmPoolManager(
        get_runner_settings(),
        workstation_event_publisher=get_workstation_event_publisher(),
    )


__all__ = [
    "get_event_publisher",
    "get_runner_settings",
    "get_workstation_event_publisher",
    "get_warm_pool_manager",
    "get_session_manager",
    "get_vnc_controller",
]
