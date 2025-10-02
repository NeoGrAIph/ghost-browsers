"""FastAPI router exposing warm workstation management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..dependencies import get_warm_pool_manager
from ..warm_pool import (
    WarmPoolManager,
    WarmPoolReservation,
    WarmPoolSnapshot,
    WarmPoolState,
    WarmPoolStateError,
)

__all__ = ["router"]

router = APIRouter(prefix="/workstations", tags=["workstations"])

WarmPoolManagerDep = Annotated[WarmPoolManager, Depends(get_warm_pool_manager)]


class WorkstationSnapshotModel(BaseModel):
    """Serialised representation of a warm pool workstation snapshot."""

    workstation_id: str = Field(description="Identifier of the workstation slot")
    fingerprint_id: str | None = Field(
        default=None, description="Fingerprint assigned to the workstation"
    )
    proxy_url: str | None = Field(
        default=None,
        description="Proxy URL associated with the workstation when configured",
    )
    state: WarmPoolState = Field(description="Internal warm pool state of the workstation")

    @classmethod
    def from_snapshot(cls, snapshot: WarmPoolSnapshot) -> "WorkstationSnapshotModel":
        """Create a response model from a :class:`WarmPoolSnapshot`."""

        return cls(
            workstation_id=snapshot.workstation_id,
            fingerprint_id=snapshot.fingerprint_id,
            proxy_url=snapshot.proxy_url,
            state=snapshot.state,
        )


class WorkstationListResponse(BaseModel):
    """Response model containing warm workstation snapshots."""

    items: list[WorkstationSnapshotModel] = Field(
        default_factory=list,
        description="Collection of workstation snapshots in the warm pool",
    )


class WorkstationReservationRequest(BaseModel):
    """Request payload for reserving an idle workstation."""

    workstation_id: str | None = Field(
        default=None,
        description="Explicit workstation to reserve; pick the first idle slot when omitted",
    )


class WorkstationReservationResponse(BaseModel):
    """Response model describing a successful workstation reservation."""

    snapshot: WorkstationSnapshotModel = Field(
        description="Snapshot captured immediately after reserving the workstation",
    )
    environment: dict[str, str] = Field(
        description="Environment variables required to attach to the workstation",
    )


class WorkstationActionResponse(BaseModel):
    """Response wrapper for actions that mutate a workstation state."""

    snapshot: WorkstationSnapshotModel = Field(
        description="Snapshot captured after applying the requested transition",
    )


def _translate_state_error(exc: WarmPoolStateError) -> HTTPException:
    """Translate :class:`WarmPoolStateError` into an HTTPException."""

    message = str(exc)
    lowered = message.lower()
    status_code = status.HTTP_409_CONFLICT
    if "unknown workstation" in lowered:
        status_code = status.HTTP_404_NOT_FOUND
    return HTTPException(status_code=status_code, detail=message)


def _serialise_reservation(reservation: WarmPoolReservation) -> WorkstationReservationResponse:
    """Convert ``reservation`` into the public response model."""

    snapshot_model = WorkstationSnapshotModel.from_snapshot(reservation.snapshot)
    return WorkstationReservationResponse(
        snapshot=snapshot_model,
        environment=dict(reservation.environment),
    )


def _serialise_snapshot(snapshot: WarmPoolSnapshot) -> WorkstationActionResponse:
    """Convert ``snapshot`` to a :class:`WorkstationActionResponse`."""

    return WorkstationActionResponse(snapshot=WorkstationSnapshotModel.from_snapshot(snapshot))


@router.get(
    "",
    response_model=WorkstationListResponse,
    summary="List warm workstation slots",
)
async def list_workstations(manager: WarmPoolManagerDep) -> WorkstationListResponse:
    """Return warm pool snapshots for all configured workstations."""

    items = [
        WorkstationSnapshotModel.from_snapshot(snapshot) for snapshot in manager.list_slots()
    ]
    return WorkstationListResponse(items=items)


@router.post(
    "/reserve",
    response_model=WorkstationReservationResponse,
    summary="Reserve an idle workstation",
)
async def reserve_workstation(
    payload: WorkstationReservationRequest,
    manager: WarmPoolManagerDep,
) -> WorkstationReservationResponse:
    """Reserve an idle workstation slot and expose its launch environment."""

    try:
        reservation = await manager.reserve_slot(payload.workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_reservation(reservation)


@router.post(
    "/{workstation_id}/busy",
    response_model=WorkstationActionResponse,
    summary="Mark a reserved workstation as busy",
)
async def mark_workstation_busy(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Transition ``workstation_id`` from reserved to busy state."""

    try:
        snapshot = await manager.mark_busy(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)


@router.post(
    "/{workstation_id}/cancel",
    response_model=WorkstationActionResponse,
    summary="Cancel a workstation reservation",
)
async def cancel_workstation_reservation(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Return ``workstation_id`` to idle when reservation setup fails."""

    try:
        snapshot = await manager.cancel_reservation(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)


@router.post(
    "/{workstation_id}/release",
    response_model=WorkstationActionResponse,
    summary="Release a busy workstation",
)
async def release_workstation(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Recycle ``workstation_id`` back to the idle pool."""

    try:
        snapshot = await manager.release_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)


@router.post(
    "/{workstation_id}/restart",
    response_model=WorkstationActionResponse,
    summary="Restart a warm workstation",
)
async def restart_workstation(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Force a workstation to recycle its browser process."""

    try:
        snapshot = await manager.restart_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)


@router.post(
    "/{workstation_id}/drain",
    response_model=WorkstationActionResponse,
    summary="Drain a warm workstation",
)
async def drain_workstation(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Stop using ``workstation_id`` for new reservations until re-enabled."""

    try:
        snapshot = await manager.drain_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)


@router.post(
    "/{workstation_id}/enable",
    response_model=WorkstationActionResponse,
    summary="Enable a drained workstation",
)
async def enable_workstation(
    workstation_id: str,
    manager: WarmPoolManagerDep,
) -> WorkstationActionResponse:
    """Bring a drained workstation back into service."""

    try:
        snapshot = await manager.enable_slot(workstation_id)
    except WarmPoolStateError as exc:
        raise _translate_state_error(exc) from exc
    return _serialise_snapshot(snapshot)
