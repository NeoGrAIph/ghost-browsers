"""Request models used when launching sessions via the gateway."""

from __future__ import annotations

from typing import Any

from core import SessionProxySettings, SessionStatus, SessionVncDetails, StartUrlWait
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, PositiveInt


class SessionLaunchPayload(BaseModel):
    """Describe the JSON contract for ``POST /sessions`` requests.

    Attributes:
        status: Desired initial :class:`~core.SessionStatus` for the session.
        headless: Whether the browser should omit VNC streaming support.
        idle_ttl_seconds: Soft timeout (seconds) before idle sessions are reaped.
        start_url: Optional URL opened after the session boots.
        start_url_wait: Loading strategy applied to ``start_url``.
        browser: Browser family requested by the operator.
        labels: Arbitrary key/value tags attached to the session.
        metadata: Free-form metadata persisted with the session.
        proxy: Proxy configuration forwarded to the runner.
        vnc: Runner-supplied VNC details, if any.
        vnc_enabled: Explicit override for VNC availability (``None`` -> auto).
    """

    model_config = ConfigDict(extra="forbid")

    status: SessionStatus = Field(default=SessionStatus.INIT)
    headless: bool = Field(default=False)
    idle_ttl_seconds: PositiveInt = Field(default=300, ge=30, le=3600)
    start_url: AnyUrl | None = Field(default=None)
    start_url_wait: StartUrlWait = Field(default=StartUrlWait.LOAD)
    browser: str = Field(default="camoufox", min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    proxy: SessionProxySettings | None = Field(default=None)
    vnc: SessionVncDetails | None = Field(default=None)
    vnc_enabled: bool | None = Field(default=None)
