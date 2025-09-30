"""Configuration models for the worker service."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionDefaults(BaseModel):
    """Default session parameters loaded from configuration."""

    idle_ttl_seconds: Annotated[int, Field(ge=30, le=3600)] = 300
    headless: bool = False


class WorkerSettings(BaseSettings):
    """Runtime settings for the worker service."""

    # Use ``WORKER_`` as a prefix so environment variables like
    # ``WORKER_HOST`` override these defaults.  ``.env`` is loaded for local
    # development convenience.
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=".env")

    # Host/port pair passed to ``uvicorn`` when the service is executed.
    host: str = "0.0.0.0"
    port: int = 8080
    # How long to wait for the event loop to finish background tasks before the
    # process is forcefully terminated.
    shutdown_timeout: int = 10

    # Path at which the Prometheus metrics registry should be exposed.
    metrics_endpoint: str = "/metrics"

    # Default values used when clients omit optional fields for session
    # creation.  ``cleanup_interval`` defines how often stale sessions are
    # garbage collected by the runner.
    session_defaults: SessionDefaults = Field(default_factory=SessionDefaults)
    cleanup_interval: Annotated[int, Field(gt=0, le=3600)] = 15

    # Connection parameters for the runner sidecar.  ``supports_vnc`` is a flag
    # that controls VNC-specific API features in handlers.
    runner_base_url: str = "http://127.0.0.1:8070"
    supports_vnc: bool = False


@lru_cache
def load_settings() -> WorkerSettings:
    """Return cached settings instance."""

    return WorkerSettings()


__all__ = ["WorkerSettings", "load_settings"]
