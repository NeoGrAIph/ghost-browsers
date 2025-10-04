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
    """Representation of a runner enriched with UI-facing health and capability data."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Runner identifier")
    base_url: AnyUrl = Field(description="Runner control-plane base URL")
    state: RunnerState = Field(description="Operational state reported by discovery")
    total_slots: int = Field(description="Maximum concurrent sessions")
    available_slots: int = Field(description="Currently free slots")
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
    capabilities: list[str] = Field(
        default_factory=list,
        description="Capability flags advertised by the runner (e.g. 'browser:camoufox|Camoufox')",
    )


@router.get("", response_model=list[RunnerStatus])
async def list_runners(
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[RunnerStatus]:
    """Return all registered runners together with their health metadata."""

    runners = await registry.list()
    snapshots: list[RunnerStatus] = []
    for runner in runners:
        payload = runner.model_dump()
        payload["capabilities"] = sorted(runner.capabilities)
        snapshots.append(RunnerStatus.model_validate(payload))
    return snapshots
