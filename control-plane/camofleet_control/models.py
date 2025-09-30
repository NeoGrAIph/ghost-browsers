"""Pydantic models used by the control-plane API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class WorkerStatus(BaseModel):
    """Snapshot of a worker's health response."""

    name: str
    healthy: bool
    detail: dict[str, Any]
    supports_vnc: bool


class SessionDescriptor(BaseModel):
    """Aggregate information about a session across the fleet."""

    worker: str
    id: str
    status: str
    created_at: datetime
    last_seen_at: datetime
    browser: str
    headless: bool
    idle_ttl_seconds: int
    labels: dict[str, str]
    ws_endpoint: str
    vnc_enabled: bool | None = None
    vnc: dict[str, Any]
    start_url_wait: Literal["none", "domcontentloaded", "load"] | None = None


class CreateSessionRequest(BaseModel):
    """Incoming payload when users request a new session."""

    worker: str | None = None
    headless: bool | None = None
    idle_ttl_seconds: int | None = None
    labels: dict[str, str] | None = None
    start_url: str | None = None
    vnc: bool = False
    start_url_wait: Literal["none", "domcontentloaded", "load"] | None = None


class CreateSessionResponse(SessionDescriptor):
    """Session representation returned by POST /sessions."""


__all__ = [
    "WorkerStatus",
    "SessionDescriptor",
    "CreateSessionRequest",
    "CreateSessionResponse",
]
