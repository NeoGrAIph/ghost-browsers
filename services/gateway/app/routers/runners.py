"""Runner discovery endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from core import RunnerState
from fastapi import APIRouter, Depends
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from ..deps import get_runner_registry
from ..deps.security import get_current_user
from ..security import AuthenticatedUser
from ..services.runner_registry import RunnerRegistry

router = APIRouter(prefix="/runners", tags=["runners"])


class RunnerStatus(BaseModel):
    """Representation of a runner enriched with health metadata for the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Runner identifier")
    base_url: AnyUrl = Field(description="Runner control-plane base URL")
    state: RunnerState = Field(description="Operational state reported by discovery")
    total_slots: int | None = Field(
        default=None,
        description="Maximum concurrent sessions when bounded",
    )
    available_slots: int | None = Field(
        default=None,
        description="Currently free slots when the runner reports capacity",
    )
    healthy: bool = Field(description="Latest health probe outcome")
    supports_vnc: bool = Field(description="Runner can serve VNC sessions")
    last_heartbeat_at: datetime | None = Field(
        default=None,
        description="Timestamp of the last successful health probe",
    )
    vnc_http_url_template: str | None = Field(
        default=None,
        description="Public HTTP VNC template exposed through the gateway",
    )
    vnc_ws_url_template: str | None = Field(
        default=None,
        description="Public WebSocket VNC template exposed through the gateway",
    )


@router.get("", response_model=list[RunnerStatus])
async def list_runners(
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[RunnerStatus]:
    """Return all registered runners together with their health metadata."""

    runners = await registry.list()
    return [RunnerStatus.model_validate(runner) for runner in runners]
