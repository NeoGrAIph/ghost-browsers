"""Runtime configuration model for the Runner service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)


class RunnerSettings(BaseModel):
    """Typed view over environment-driven runner configuration.

    The settings object captures values that influence how the runner allocates
    sessions, exposes diagnostics, and emits events. ``from_env`` reads
    recognised environment variables and applies type validation, making it
    safe to inject into FastAPI dependencies and background components.

    Attributes:
        runner_id: Identifier advertised to the gateway/UI for every session.
        camoufox_path: Absolute path to the Camoufox binary.
        event_endpoint: Optional HTTP(S) endpoint used by the event publisher
            stub. When absent, events are kept in-memory.
        slot_limit: Maximum number of concurrently active sessions.
        warm_pool_config_path: Optional path to a JSON file describing the warm
            workstation pool.
        vnc_enabled: Controls whether VNC URLs should be generated for new
            sessions.
        vnc_http_base_url: Base URL for generating human-facing VNC previews.
        vnc_ws_base_url: Base URL for generating WebSocket control endpoints.
        vnc_token_ttl_seconds: Time-to-live applied to generated VNC tokens.
        proxy_enabled: Signals whether proxy support is globally available for
            sessions provisioned by this runner.
        proxy_http_base_url: Optional base URL for HTTP proxies issued during
            session creation.
        proxy_https_base_url: Optional base URL for HTTPS proxies issued during
            session creation.
        proxy_socks_base_url: Optional base URL for SOCKS proxies issued during
            session creation.
        browser_prefs_path: Optional path to JSON encoded browser preferences
            shared across prewarmed sessions.
        prewarm_navigation: Controls whether the runner navigates to a
            ``start_url`` during prewarming.
        start_url: Optional initial URL used during prewarm navigation.
        start_url_wait_ms: Delay in milliseconds to wait after hitting the
            ``start_url`` before considering prewarm complete.
        prewarm_failure_history_size: Number of most recent prewarm failures to
            retain for diagnostics.

    Example:
        >>> settings = RunnerSettings.from_env({"RUNNER_ID": "runner-1"})
        >>> settings.runner_id
        'runner-1'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    runner_id: str = Field(default="runner-local", min_length=1)
    camoufox_path: Path = Field(default=Path("/usr/bin/camoufox"))
    event_endpoint: AnyUrl | None = Field(default=None)
    slot_limit: PositiveInt = Field(default=4, ge=1)
    warm_pool_config_path: Path | None = Field(
        default=None,
        description="Path to the warm pool configuration JSON file",
    )
    vnc_enabled: bool = Field(default=True)
    vnc_http_base_url: AnyUrl = Field(default="http://127.0.0.1:8060/vnc")
    vnc_ws_base_url: AnyUrl = Field(default="ws://127.0.0.1:8060/vnc")
    vnc_display_min: PositiveInt = Field(default=100, ge=1, le=1024)
    vnc_display_max: PositiveInt = Field(default=199, ge=1, le=1024)
    vnc_port_min: PositiveInt = Field(default=5900, ge=1024, le=65535)
    vnc_port_max: PositiveInt = Field(default=5999, ge=1024, le=65535)
    vnc_ws_port_min: PositiveInt = Field(default=6900, ge=1024, le=65535)
    vnc_ws_port_max: PositiveInt = Field(default=6999, ge=1024, le=65535)
    vnc_resolution: str = Field(default="1920x1080x24")
    vnc_web_assets_path: Path | None = Field(default=Path("/usr/share/novnc"))
    vnc_startup_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    vnc_token_ttl_seconds: PositiveInt = Field(default=120, le=300)
    proxy_enabled: bool = Field(default=False)
    proxy_http_base_url: AnyUrl | None = Field(default=None)
    proxy_https_base_url: AnyUrl | None = Field(default=None)
    proxy_socks_base_url: AnyUrl | None = Field(default=None)
    browser_prefs_path: Path | None = Field(
        default=None,
        description="Path to shared browser preference overrides",
    )
    prewarm_navigation: bool = Field(
        default=False,
        description="Whether to navigate to start_url during prewarm",
    )
    start_url: AnyUrl | None = Field(
        default=None,
        description="Optional landing URL used during session prewarm",
    )
    start_url_wait_ms: NonNegativeInt = Field(
        default=0,
        description="Milliseconds to wait after navigating to the start_url",
    )
    prewarm_failure_history_size: PositiveInt = Field(default=5, ge=1, le=50)

    @model_validator(mode="after")
    def _validate_vnc_ranges(self) -> "RunnerSettings":
        """Ensure VNC port and display ranges are coherent."""

        if self.vnc_display_min > self.vnc_display_max:
            raise ValueError("vnc_display_min must be <= vnc_display_max")
        if self.vnc_port_min > self.vnc_port_max:
            raise ValueError("vnc_port_min must be <= vnc_port_max")
        if self.vnc_ws_port_min > self.vnc_ws_port_max:
            raise ValueError("vnc_ws_port_min must be <= vnc_ws_port_max")
        display_span = self.vnc_display_max - self.vnc_display_min + 1
        vnc_span = self.vnc_port_max - self.vnc_port_min + 1
        ws_span = self.vnc_ws_port_max - self.vnc_ws_port_min + 1
        if min(display_span, vnc_span, ws_span) <= 0:
            raise ValueError("VNC resource ranges must include at least one value")
        return self

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "RunnerSettings":
        """Load settings from the provided environment mapping.

        Args:
            environ: Mapping resembling :data:`os.environ`. When ``None`` the
                real process environment is used.

        Returns:
            RunnerSettings: Parsed and validated settings instance.
        """

        source: dict[str, Any] = {}
        env = os.environ if environ is None else environ
        if "RUNNER_ID" in env:
            source["runner_id"] = env["RUNNER_ID"]
        if "CAMOUFOX_PATH" in env:
            source["camoufox_path"] = Path(env["CAMOUFOX_PATH"])
        if "EVENT_ENDPOINT" in env:
            source["event_endpoint"] = env["EVENT_ENDPOINT"]
        if "SLOT_LIMIT" in env:
            source["slot_limit"] = int(env["SLOT_LIMIT"])
        if "WARM_POOL_CONFIG_PATH" in env:
            raw = env["WARM_POOL_CONFIG_PATH"].strip()
            source["warm_pool_config_path"] = Path(raw) if raw else None
        if "VNC_ENABLED" in env:
            source["vnc_enabled"] = env["VNC_ENABLED"].lower() in {"1", "true", "yes"}
        if "VNC_HTTP_BASE_URL" in env:
            source["vnc_http_base_url"] = env["VNC_HTTP_BASE_URL"]
        if "VNC_WS_BASE_URL" in env:
            source["vnc_ws_base_url"] = env["VNC_WS_BASE_URL"]
        if "VNC_TOKEN_TTL_SECONDS" in env:
            source["vnc_token_ttl_seconds"] = int(env["VNC_TOKEN_TTL_SECONDS"])
        if "VNC_DISPLAY_MIN" in env:
            source["vnc_display_min"] = int(env["VNC_DISPLAY_MIN"])
        if "VNC_DISPLAY_MAX" in env:
            source["vnc_display_max"] = int(env["VNC_DISPLAY_MAX"])
        if "VNC_PORT_MIN" in env:
            source["vnc_port_min"] = int(env["VNC_PORT_MIN"])
        if "VNC_PORT_MAX" in env:
            source["vnc_port_max"] = int(env["VNC_PORT_MAX"])
        if "VNC_WS_PORT_MIN" in env:
            source["vnc_ws_port_min"] = int(env["VNC_WS_PORT_MIN"])
        if "VNC_WS_PORT_MAX" in env:
            source["vnc_ws_port_max"] = int(env["VNC_WS_PORT_MAX"])
        if "VNC_RESOLUTION" in env:
            source["vnc_resolution"] = env["VNC_RESOLUTION"]
        if "VNC_WEB_ASSETS_PATH" in env:
            source["vnc_web_assets_path"] = Path(env["VNC_WEB_ASSETS_PATH"])
        if "VNC_STARTUP_TIMEOUT_SECONDS" in env:
            source["vnc_startup_timeout_seconds"] = float(
                env["VNC_STARTUP_TIMEOUT_SECONDS"]
            )
        if "PROXY_ENABLED" in env:
            source["proxy_enabled"] = env["PROXY_ENABLED"].lower() in {"1", "true", "yes"}
        if "PROXY_HTTP_BASE_URL" in env:
            source["proxy_http_base_url"] = env["PROXY_HTTP_BASE_URL"]
        if "PROXY_HTTPS_BASE_URL" in env:
            source["proxy_https_base_url"] = env["PROXY_HTTPS_BASE_URL"]
        if "PROXY_SOCKS_BASE_URL" in env:
            source["proxy_socks_base_url"] = env["PROXY_SOCKS_BASE_URL"]
        if "BROWSER_PREFS_PATH" in env:
            raw = env["BROWSER_PREFS_PATH"].strip()
            source["browser_prefs_path"] = Path(raw) if raw else None
        if "PREWARM_NAVIGATION" in env:
            source["prewarm_navigation"] = env["PREWARM_NAVIGATION"].lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        if "START_URL" in env:
            raw_url = env["START_URL"].strip()
            source["start_url"] = raw_url or None
        if "START_URL_WAIT_MS" in env:
            source["start_url_wait_ms"] = int(env["START_URL_WAIT_MS"])
        if "PREWARM_FAILURE_HISTORY_SIZE" in env:
            source["prewarm_failure_history_size"] = int(env["PREWARM_FAILURE_HISTORY_SIZE"])
        return cls.model_validate(source)


__all__ = ["RunnerSettings"]
