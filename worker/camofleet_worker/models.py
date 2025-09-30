"""Pydantic models shared by the worker API endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Lifecycle states for a session."""

    INIT = "INIT"
    READY = "READY"
    TERMINATING = "TERMINATING"
    DEAD = "DEAD"


class SessionCreateRequest(BaseModel):
    """Inbound payload for creating a new browser session."""

    # ``None`` means "use the worker default".  It allows the API consumer to
    # keep requests minimal while still supporting overrides when needed.
    headless: bool | None = None
    idle_ttl_seconds: Annotated[int | None, Field(ge=30, le=3600)] = None
    start_url: Annotated[str | None, Field(max_length=1024)] = None
    start_url_wait: Literal["none", "domcontentloaded", "load"] | None = None
    # ``labels`` propagate opaque metadata from clients to other components.
    labels: dict[str, str] | None = None
    # Request VNC support for the session (if the worker supports it).
    vnc: bool = False


class SessionSummary(BaseModel):
    """Short session description returned by most list endpoints."""

    id: str
    status: SessionStatus
    created_at: datetime
    last_seen_at: datetime
    browser: str
    headless: bool
    idle_ttl_seconds: int
    labels: dict[str, str]
    worker_id: str
    vnc_enabled: bool
    start_url_wait: Literal["none", "domcontentloaded", "load"]


class SessionDetail(SessionSummary):
    """Extended session representation used by the worker UI."""

    # Public websocket path that the control plane exposes for tunnelling.
    ws_endpoint: str
    # VNC metadata (hostnames, ports) is dynamic and therefore stored in a free
    # form mapping instead of a rigid model.  Values may be ``None`` if the
    # runner has not assigned resources yet.
    vnc: dict[str, str | bool | None]


class SessionDeleteResponse(BaseModel):
    """Response returned after scheduling a deletion."""

    id: str
    status: SessionStatus


class HealthResponse(BaseModel):
    """Simple health payload."""

    status: str
    version: str
    checks: dict[str, str]


__all__ = [
    "SessionStatus",
    "SessionCreateRequest",
    "SessionSummary",
    "SessionDetail",
    "SessionDeleteResponse",
    "HealthResponse",
]
