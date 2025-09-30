"""Configuration objects for the control-plane service."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerConfig(BaseModel):
    """Describe a worker entry."""

    name: Annotated[str, Field(min_length=1)]
    url: Annotated[str, Field(min_length=1)]
    # Optional overrides for VNC endpoints.  When omitted the control plane will
    # fall back to the worker URL, which is suitable for co-located services.
    vnc_ws: str | None = None
    vnc_http: str | None = None
    supports_vnc: bool = False


class ControlSettings(BaseSettings):
    """Runtime configuration."""

    # ``CONTROL_`` mirrors the worker service approach and keeps environment
    # variables predictable.  ``.env`` is loaded to simplify local development.
    model_config = SettingsConfigDict(env_prefix="CONTROL_", env_file=".env")

    host: str = "0.0.0.0"
    port: int = 9000
    # The control plane can operate with zero workers configured, but shipping a
    # sensible default helps newcomers run ``docker compose up`` without extra
    # tweaks.
    workers: list[WorkerConfig] = Field(
        default_factory=lambda: [
            WorkerConfig(
                name="local",
                url="http://worker:8080",
                supports_vnc=False,
            ),
        ]
    )
    # HTTP timeout used for all interactions with workers.
    request_timeout: float = 10.0
    # Public prefix allows hosting the API under a sub-path (e.g. behind a
    # reverse proxy).
    public_api_prefix: str = "/"


@lru_cache
def load_settings() -> ControlSettings:
    """Load and cache settings for the lifetime of the process."""

    return ControlSettings()


__all__ = ["ControlSettings", "WorkerConfig", "load_settings"]
