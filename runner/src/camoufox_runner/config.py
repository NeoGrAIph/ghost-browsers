"""Declarative configuration for the Camoufox runner."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionDefaults(BaseModel):
    """Default session parameters."""

    idle_ttl_seconds: Annotated[int, Field(ge=30, le=3600)] = 300
    headless: bool = False
    start_url: str | None = None


class RunnerSettings(BaseSettings):
    """Runtime settings for the runner."""

    model_config = SettingsConfigDict(env_prefix="RUNNER_", env_file=".env")

    host: str = "0.0.0.0"
    port: int = 8070
    metrics_endpoint: str = "/metrics"
    cleanup_interval: Annotated[int, Field(gt=0, le=3600)] = 15
    session_defaults: SessionDefaults = Field(default_factory=SessionDefaults)
    vnc_ws_base: str | None = None
    vnc_http_base: str | None = None
    vnc_display_min: Annotated[int, Field(ge=1, le=1024)] = 100
    vnc_display_max: Annotated[int, Field(ge=1, le=1024)] = 199
    vnc_port_min: Annotated[int, Field(ge=1024, le=65535)] = 5900
    vnc_port_max: Annotated[int, Field(ge=1024, le=65535)] = 5999
    vnc_ws_port_min: Annotated[int, Field(ge=1024, le=65535)] = 6900
    vnc_ws_port_max: Annotated[int, Field(ge=1024, le=65535)] = 6999
    vnc_resolution: str = "1920x1080x24"
    vnc_web_assets_path: str | None = "/usr/share/novnc"
    vnc_startup_timeout_seconds: Annotated[float, Field(gt=0.0, le=30.0)] = 5.0
    start_url_wait: Literal["none", "domcontentloaded", "load"] = "load"
    disable_ipv6: bool = True
    disable_http3: bool = True
    disable_webrtc: bool = True

    # Prewarm pool: keep a small number of ready-to-serve browser servers
    # Separate targets for headless (no VNC) and VNC sessions
    prewarm_headless: Annotated[int, Field(ge=0, le=64)] = 1
    prewarm_vnc: Annotated[int, Field(ge=0, le=64)] = 1
    prewarm_check_interval_seconds: Annotated[float, Field(gt=0.1, le=60.0)] = 2.0

    @model_validator(mode="after")
    def _validate_vnc_ranges(self) -> "RunnerSettings":
        """Ensure VNC resource ranges are sensible."""

        if self.vnc_display_min > self.vnc_display_max:
            raise ValueError("vnc_display_min must be less than or equal to vnc_display_max")
        if self.vnc_port_min > self.vnc_port_max:
            raise ValueError("vnc_port_min must be less than or equal to vnc_port_max")
        if self.vnc_ws_port_min > self.vnc_ws_port_max:
            raise ValueError("vnc_ws_port_min must be less than or equal to vnc_ws_port_max")
        display_span = self.vnc_display_max - self.vnc_display_min + 1
        vnc_span = self.vnc_port_max - self.vnc_port_min + 1
        ws_span = self.vnc_ws_port_max - self.vnc_ws_port_min + 1
        capacity = min(display_span, vnc_span, ws_span)
        if capacity <= 0:
            raise ValueError("VNC resource ranges must contain at least one value")
        return self


@lru_cache
def load_settings() -> RunnerSettings:
    """Return cached settings instance."""

    return RunnerSettings()


__all__ = ["RunnerSettings", "load_settings", "SessionDefaults"]
