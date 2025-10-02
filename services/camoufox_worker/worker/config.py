"""Configuration models powering the Camoufox worker service."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionDefaults(BaseModel):
    """Default session parameters applied when clients omit optional fields."""

    idle_ttl_seconds: Annotated[int, Field(ge=30, le=3600)] = 300
    headless: bool = False
    start_url_wait: str = Field(default="load", pattern="^(none|domcontentloaded|load)$")


class WorkerSettings(BaseSettings):
    """Runtime settings sourced from environment variables and `.env` files.

    Attributes
    ----------
    host:
        Host interface exposed by the FastAPI application (defaults to
        ``0.0.0.0`` for container compatibility).
    port:
        TCP port used by the HTTP server. This value is not consumed directly
        by the ASGI application but is provided for entrypoint scripts.
    shutdown_timeout:
        Grace period in seconds granted to background tasks during shutdown.
    metrics_endpoint:
        URL path for exposing Prometheus metrics collected by the worker.
    session_defaults:
        Default parameters merged into session creation requests when the
        client leaves a field unset.
    cleanup_interval:
        How often, in seconds, the worker should instruct the runner to purge
        stale sessions. The value mirrors the beta branch implementation to
        simplify deployment.
    runner_base_url:
        Base URL of the Camoufox runner sidecar proxied by this worker.
    supports_vnc:
        Flag indicating whether this worker instance can provision VNC-backed
        sessions. The create endpoint rejects ``vnc=true`` when the flag is
        ``False``.
    browser_required_flags:
        Mapping of mandatory browser launch flags applied to every session.
        Values are opaque for the worker and passed straight to the runner via
        session metadata. The structure intentionally accepts arbitrary keys to
        avoid code changes when operators adjust launch options in Helm charts
        or Compose files.
    """

    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    shutdown_timeout: int = 10
    metrics_endpoint: str = "/metrics"
    session_defaults: SessionDefaults = Field(default_factory=SessionDefaults)
    cleanup_interval: Annotated[int, Field(gt=0, le=3600)] = 15
    runner_base_url: str = "http://127.0.0.1:8070"
    supports_vnc: bool = False
    browser_required_flags: dict[str, Any] = Field(default_factory=dict)


@lru_cache
def load_settings() -> WorkerSettings:
    """Return a cached :class:`WorkerSettings` instance."""

    return WorkerSettings()


__all__ = ["WorkerSettings", "SessionDefaults", "load_settings"]

