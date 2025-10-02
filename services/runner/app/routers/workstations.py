"""Warm workstation management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..dependencies import get_warm_pool_manager
from ..warm_pool import (
    WarmPoolManager,
    WarmPoolSnapshot,
    WarmPoolState,
    WarmPoolStateError,
)


class WorkstationSnapshot(BaseModel):
    """Serializable representation of a warm workstation slot.

    Args:
        workstation_id: Identifier of the warm workstation slot.
        fingerprint_id: Optional fingerprint affinity associated with the slot.
        proxy_url: Optional proxy override configured for the workstation.
        state: Current lifecycle state reported by the warm pool manager.

    Example:
        >>> WorkstationSnapshot.from_snapshot(
        ...     WarmPoolSnapshot(
        ...         workstation_id="ws-1",
        ...         fingerprint_id="fp-1",
        ...         proxy_url=None,
        ...         state=WarmPoolState.IDLE,
        ...     )
        ... )  # doctest: +SKIP
    """

    workstation_id: str
    fingerprint_id: str | None
    proxy_url: str | None
    state: WarmPoolState

    @classmethod
    def from_snapshot(cls, snapshot: WarmPoolSnapshot) -> "WorkstationSnapshot":
        """Build a response model from ``snapshot``."""

        return cls(
            workstation_id=snapshot.workstation_id,
            fingerprint_id=snapshot.fingerprint_id,
            proxy_url=snapshot.proxy_url,
            state=snapshot.state,
        )


router = APIRouter(prefix="/workstations", tags=["workstations"])

WarmPoolManagerDep = Annotated[WarmPoolManager, Depends(get_warm_pool_manager)]


async def _ensure_started(manager: WarmPoolManager) -> None:
    """Start the warm pool lazily when no slots have been provisioned yet."""

    marker = "__workstations_router_started__"
    if getattr(manager, marker, False):  # pragma: no cover - defensive guard
        return
    if manager.list_slots():
        setattr(manager, marker, True)
        return
    await manager.start()
    setattr(manager, marker, True)


def _translate_state_error(exc: WarmPoolStateError) -> HTTPException:
    """Map ``WarmPoolStateError`` instances to HTTP responses."""

    detail = str(exc)
    status_code = status.HTTP_409_CONFLICT
    if "unknown workstation" in detail:
        status_code = status.HTTP_404_NOT_FOUND
    return HTTPException(status_code=status_code, detail=detail)


@router.get("", response_model=list[WorkstationSnapshot])
async def list_workstations(manager: WarmPoolManagerDep) -> list[WorkstationSnapshot]:
    """Return snapshots for all warm workstation slots."""

    await _ensure_started(manager)
    return [WorkstationSnapshot.from_snapshot(s) for s in manager.list_slots()]


@router.post(
    "/{workstation_id}/restart",
    response_model=WorkstationSnapshot,
    status_code=status.HTTP_200_OK,
)
async def restart_workstation(
    workstation_id: str, manager: WarmPoolManagerDep
) -> WorkstationSnapshot:
    """Recycle the warm workstation and provision a fresh browser instance."""

    await _ensure_started(manager)
    try:
        snapshot = await manager.restart_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return WorkstationSnapshot.from_snapshot(snapshot)


@router.post(
    "/{workstation_id}/drain",
    response_model=WorkstationSnapshot,
    status_code=status.HTTP_200_OK,
)
async def drain_workstation(
    workstation_id: str, manager: WarmPoolManagerDep
) -> WorkstationSnapshot:
    """Mark a warm workstation as draining and tear down its resources."""

    await _ensure_started(manager)
    try:
        snapshot = await manager.drain_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return WorkstationSnapshot.from_snapshot(snapshot)


@router.post(
    "/{workstation_id}/enable",
    response_model=WorkstationSnapshot,
    status_code=status.HTTP_200_OK,
)
async def enable_workstation(
    workstation_id: str, manager: WarmPoolManagerDep
) -> WorkstationSnapshot:
    """Re-enable a previously drained warm workstation."""

    await _ensure_started(manager)
    try:
        snapshot = await manager.enable_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return WorkstationSnapshot.from_snapshot(snapshot)


__all__ = [
    "WorkstationSnapshot",
    "drain_workstation",
    "enable_workstation",
    "list_workstations",
    "restart_workstation",
    "router",
]
