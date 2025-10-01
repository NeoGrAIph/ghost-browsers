"""Dependency wiring for the session manager and publishers."""

from __future__ import annotations

from functools import lru_cache

from ..config import RunnerSettings
from ..events import (
    HttpSessionEventPublisher,
    InMemorySessionEventPublisher,
    SessionEventPublisher,
)
from ..session_manager import SessionManager


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
def get_session_manager() -> SessionManager:
    """Return a singleton :class:`SessionManager` wired with default dependencies."""

    return SessionManager(get_runner_settings(), get_event_publisher())


__all__ = [
    "get_event_publisher",
    "get_runner_settings",
    "get_session_manager",
]
