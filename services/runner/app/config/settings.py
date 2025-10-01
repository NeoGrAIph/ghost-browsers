"""Runtime configuration model for the Runner service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, PositiveInt


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
    vnc_enabled: bool = Field(default=True)
    vnc_http_base_url: AnyUrl = Field(default="http://127.0.0.1:8060/vnc")
    vnc_ws_base_url: AnyUrl = Field(default="ws://127.0.0.1:8060/vnc")
    vnc_token_ttl_seconds: PositiveInt = Field(default=120, le=300)
    proxy_enabled: bool = Field(default=False)
    proxy_http_base_url: AnyUrl | None = Field(default=None)
    proxy_https_base_url: AnyUrl | None = Field(default=None)
    proxy_socks_base_url: AnyUrl | None = Field(default=None)
    prewarm_failure_history_size: PositiveInt = Field(default=5, ge=1, le=50)

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
        if "VNC_ENABLED" in env:
            source["vnc_enabled"] = env["VNC_ENABLED"].lower() in {"1", "true", "yes"}
        if "VNC_HTTP_BASE_URL" in env:
            source["vnc_http_base_url"] = env["VNC_HTTP_BASE_URL"]
        if "VNC_WS_BASE_URL" in env:
            source["vnc_ws_base_url"] = env["VNC_WS_BASE_URL"]
        if "VNC_TOKEN_TTL_SECONDS" in env:
            source["vnc_token_ttl_seconds"] = int(env["VNC_TOKEN_TTL_SECONDS"])
        if "PROXY_ENABLED" in env:
            source["proxy_enabled"] = env["PROXY_ENABLED"].lower() in {"1", "true", "yes"}
        if "PROXY_HTTP_BASE_URL" in env:
            source["proxy_http_base_url"] = env["PROXY_HTTP_BASE_URL"]
        if "PROXY_HTTPS_BASE_URL" in env:
            source["proxy_https_base_url"] = env["PROXY_HTTPS_BASE_URL"]
        if "PROXY_SOCKS_BASE_URL" in env:
            source["proxy_socks_base_url"] = env["PROXY_SOCKS_BASE_URL"]
        if "PREWARM_FAILURE_HISTORY_SIZE" in env:
            source["prewarm_failure_history_size"] = int(env["PREWARM_FAILURE_HISTORY_SIZE"])
        return cls.model_validate(source)


__all__ = ["RunnerSettings"]
