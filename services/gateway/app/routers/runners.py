"""Runner discovery endpoints."""

from __future__ import annotations

from typing import Annotated

from core import Runner
from fastapi import APIRouter, Depends

from ..deps import get_runner_registry
from ..deps.security import get_current_user
from ..security import AuthenticatedUser
from ..services.runner_registry import RunnerRegistry

router = APIRouter(prefix="/runners", tags=["runners"])


@router.get("", response_model=list[Runner])
async def list_runners(
    registry: Annotated[RunnerRegistry, Depends(get_runner_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[Runner]:
    """Return all registered runners."""

    return await registry.list()
