"""Configuration primitives for the VNC gateway FastAPI service.

The module defines :class:`Settings` which encapsulates environment-driven
configuration such as runner endpoints and the shared secret used to validate
VNC access tokens.  A small dependency helper :func:`get_settings` is provided
so that FastAPI endpoints can obtain a cached configuration instance via
dependency injection.  Tests may override the dependency with
``app.dependency_overrides`` to supply custom settings instances.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunnerWebsocketUrl(AnyUrl):
    """URL type constrained to WebSocket schemes."""

    allowed_schemes = {"ws", "wss"}


class Settings(BaseSettings):
    """Runtime configuration for the VNC gateway service.

    Parameters are loaded from environment variables with the ``VNC_GATEWAY_``
    prefix.  Only a minimal set of options is required for the first
    implementation: runner base URLs for HTTP and WebSocket traffic and the
    shared token secret used to authenticate clients in collaboration with the
    public Gateway component.

    Attributes
    ----------
    runner_http_base:
        Base URL (protocol + host + optional port) of the Runner service HTTP
        API.  Individual session endpoints will be appended to this base.
    runner_ws_base:
        Base URL used for establishing WebSocket tunnels to the Runner.
    token_secret:
        Shared secret string used by :class:`~app.token.TokenValidator` to
        validate HMAC based VNC tokens.
    """

    model_config = SettingsConfigDict(env_prefix="VNC_GATEWAY_", extra="ignore")

    runner_http_base: AnyHttpUrl = Field(default="http://runner:8080")
    runner_ws_base: RunnerWebsocketUrl = Field(default="ws://runner:8080")
    token_secret: str = Field(min_length=1, default="dev-secret")

@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    FastAPI caches dependencies keyed by function identity, therefore the
    ``@lru_cache`` decorator ensures that settings are created only once per
    process and reused across requests.  Tests can override this dependency by
    injecting an alternative callable in ``app.dependency_overrides``.

    Returns
    -------
    Settings
        Parsed configuration derived from environment variables.
    """

    return Settings()  # type: ignore[call-arg]


__all__ = ["Settings", "get_settings"]
