"""FastAPI dependency wiring for the VNC gateway service."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from .config import Settings, get_settings
from .metrics import ConnectionRegistry
from .proxy import RunnerProxy
from .token import TokenValidator

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_token_validator(settings: SettingsDependency) -> TokenValidator:
    """Instantiate a :class:`TokenValidator` using application settings."""

    return TokenValidator(secret=settings.token_secret)


def get_runner_proxy(settings: SettingsDependency) -> RunnerProxy:
    """Instantiate a :class:`RunnerProxy` for forwarding traffic to Runner."""

    return RunnerProxy(settings=settings)


def get_connection_registry() -> ConnectionRegistry:
    """Provide a shared :class:`ConnectionRegistry` instance.

    The registry is stored on the dependency function itself to maintain a
    process-wide singleton while keeping the implementation straightforward.
    """

    if not hasattr(get_connection_registry, "_registry"):
        get_connection_registry._registry = ConnectionRegistry()  # type: ignore[attr-defined]
    return get_connection_registry._registry  # type: ignore[attr-defined]


__all__ = [
    "get_connection_registry",
    "get_runner_proxy",
    "get_token_validator",
]
