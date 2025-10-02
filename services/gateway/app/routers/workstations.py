"""Workstation management endpoints exposed by the gateway."""

from __future__ import annotations

from typing import Annotated

from core import WorkstationEvent
from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_workstation_registry
from ..deps.security import get_current_user
from ..models.workstations import WorkstationRecord, WorkstationUpsertPayload
from ..security import AuthenticatedUser
from ..services.workstation_registry import WorkstationRegistry

router = APIRouter(prefix="/workstations", tags=["workstations"])


@router.get(
    "",
    response_model=list[WorkstationRecord],
    summary="List workstations",
    response_description="Array of workstation records tracked by the gateway",
)
async def list_workstations(
    registry: Annotated[WorkstationRegistry, Depends(get_workstation_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[WorkstationRecord]:
    """Return all workstation records currently known to the gateway.

    Args:
        registry: Registry providing access to workstation snapshots.
        user: Authenticated principal requesting the data. Included to keep the
            dependency chain consistent with other routers and audit logging.

    Returns:
        list[WorkstationRecord]: Collection of workstation records sorted by
        insertion order.

    Example:
        >>> await list_workstations(registry, user)  # doctest: +SKIP
    """

    return await registry.list()


@router.get(
    "/{workstation_id}",
    response_model=WorkstationRecord,
    summary="Get workstation",
    response_description="Workstation record identified by the path parameter",
)
async def get_workstation(
    workstation_id: str,
    registry: Annotated[WorkstationRegistry, Depends(get_workstation_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WorkstationRecord:
    """Return a single workstation record by identifier.

    Args:
        workstation_id: Identifier of the workstation to retrieve.
        registry: Registry that stores workstation metadata snapshots.
        user: Authenticated principal issuing the request.

    Returns:
        WorkstationRecord: Snapshot matching ``workstation_id``.

    Raises:
        HTTPException: If the workstation is missing from the registry.
    """

    try:
        return await registry.get(workstation_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation not found",
        ) from exc


@router.post(
    "",
    response_model=WorkstationRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Register workstation",
    response_description="Stored workstation record",
)
async def upsert_workstation(
    payload: WorkstationUpsertPayload,
    registry: Annotated[WorkstationRegistry, Depends(get_workstation_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WorkstationRecord:
    """Insert or replace workstation metadata without recording an event.

    Args:
        payload: Request body containing the workstation metadata snapshot.
        registry: Registry responsible for persisting workstation data.
        user: Authenticated principal issuing the request.

    Returns:
        WorkstationRecord: Stored record reflecting the provided metadata.
    """

    return await registry.upsert_metadata(payload.workstation)


@router.post(
    "/events",
    response_model=WorkstationRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Apply workstation event",
    response_description="Workstation record after the event has been applied",
)
async def apply_workstation_event(
    event: WorkstationEvent,
    registry: Annotated[WorkstationRegistry, Depends(get_workstation_registry)],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> WorkstationRecord:
    """Apply a workstation lifecycle event emitted by a runner.

    Args:
        event: Workstation lifecycle event sent by a runner.
        registry: Registry that will incorporate the event into stored
            snapshots.
        user: Authenticated principal issuing the request.

    Returns:
        WorkstationRecord: Updated workstation record including details from
        ``event``.
    """

    return await registry.apply_event(event)
