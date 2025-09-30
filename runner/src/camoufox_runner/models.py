"""Pydantic models that represent runner API payloads."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Lifecycle states managed by the runner."""

    INIT = "INIT"
    READY = "READY"
    TERMINATING = "TERMINATING"
    DEAD = "DEAD"


class SessionCreateRequest(BaseModel):
    """Payload accepted by ``POST /sessions``."""

    headless: bool | None = None
    idle_ttl_seconds: Annotated[int | None, Field(ge=30, le=3600)] = None
    start_url: Annotated[str | None, Field(max_length=1024)] = None
    start_url_wait: Literal["none", "domcontentloaded", "load"] | None = None
    labels: dict[str, str] | None = None
    vnc: bool = False


class SessionSummary(BaseModel):
    """Compact representation returned when listing sessions."""

    id: str
    status: SessionStatus
    created_at: datetime
    last_seen_at: datetime
    headless: bool
    idle_ttl_seconds: int
    labels: dict[str, str]
    vnc: bool
    start_url_wait: Literal["none", "domcontentloaded", "load"]


class SessionDetail(SessionSummary):
    """Extended representation that contains connection details."""

    ws_endpoint: str
    vnc_info: dict[str, str | bool | None]


class SessionDeleteResponse(BaseModel):
    """Response body returned by ``DELETE /sessions/{id}``."""

    id: str
    status: SessionStatus


class HealthResponse(BaseModel):
    """Simple health payload for readiness probes."""

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
