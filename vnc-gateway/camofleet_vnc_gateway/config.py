"""Configuration for the VNC gateway service."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="VNCGATEWAY_", env_file=".env")

    host: str = Field(default="0.0.0.0", description="Address for the HTTP server")
    port: int = Field(default=6080, ge=1, le=65535, description="Public port exposed by the gateway")
    runner_host: str = Field(
        default="runner-vnc",
        description="Hostname of the runner service reachable from the gateway",
    )
    runner_http_scheme: str = Field(default="http", pattern=r"^[a-zA-Z][a-zA-Z0-9+.-]*$")
    runner_ws_scheme: str = Field(default="ws", pattern=r"^[a-zA-Z][a-zA-Z0-9+.-]*$")
    runner_path_prefix: str = Field(
        default="",
        description="Optional path prefix prepended when contacting the runner",
    )
    min_port: int = Field(default=6900, ge=1, le=65535)
    max_port: int = Field(default=6999, ge=1, le=65535)
    request_timeout: float = Field(default=10.0, gt=0.0)

    def normalised_prefix(self) -> str:
        """Return the runner path prefix formatted for URL joins."""

        value = self.runner_path_prefix.strip()
        if not value:
            return ""
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/")

    def validate_port(self, port: str | int | None) -> int:
        """Validate that ``port`` is within the allowed range."""

        if port is None:
            raise ValueError("target_port query parameter is required")
        try:
            port_value = int(port)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("target_port must be an integer") from exc
        if port_value < self.min_port or port_value > self.max_port:
            raise ValueError("target_port outside of the allowed range")
        return port_value


@lru_cache
def load_settings() -> GatewaySettings:
    """Load settings once for the running process."""

    return GatewaySettings()


__all__ = ["GatewaySettings", "load_settings"]
