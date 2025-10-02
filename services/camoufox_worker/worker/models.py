"""Pydantic models describing the worker HTTP API surface."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Lifecycle phases mirrored from the runner implementation."""

    INIT = "INIT"
    READY = "READY"
    TERMINATING = "TERMINATING"
    DEAD = "DEAD"


class SessionCreateRequest(BaseModel):
    """Inbound payload for creating a new browser session via the worker API."""

    headless: bool | None = None
    idle_ttl_seconds: Annotated[int | None, Field(ge=30, le=3600)] = None
    start_url: Annotated[str | None, Field(max_length=1024)] = None
    start_url_wait: Literal["none", "domcontentloaded", "load"] | None = None
    labels: dict[str, str] | None = None
    vnc: bool = False
    browser_flags: dict[str, Any] | None = None


class SessionSummary(BaseModel):
    """Compact description exposed by listing endpoints."""

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
    """Extended session representation used by the UI."""

    ws_endpoint: str | None
    ws_proxy_endpoint: str | None = None
    vnc: dict[str, Any]


class SessionDeleteResponse(BaseModel):
    """Acknowledgement payload returned after scheduling a deletion."""

    id: str
    status: SessionStatus


class HealthResponse(BaseModel):
    """Structured health payload consumed by operators."""

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

