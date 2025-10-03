"""Pydantic models that shape workstation registry payloads for the gateway."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from core import WorkstationEvent, WorkstationEventType, WorkstationMeta

from pydantic import BaseModel, ConfigDict, Field


class WorkstationRecord(BaseModel):
    """Representation of a workstation tracked by the gateway API.

    Attributes:
        workstation: Full snapshot of the workstation metadata preserved in
            the registry.
        last_event_id: Identifier of the most recent workstation event applied
            to the record. ``None`` when no events have been processed yet.
        last_event_type: Type of the latest event that touched the workstation
            (for example ``workstation.created``).
        last_event_occurred_at: Timestamp describing when the latest event was
            emitted by the upstream runner.
        last_event_reason: Optional human readable reason supplied with the
            latest event.

    Example:
        >>> metadata = WorkstationMeta(
        ...     id="ws-1",
        ...     fingerprint_id="fp-1",
        ...     state="available",
        ... )
        >>> WorkstationRecord.from_metadata(metadata).workstation.id
        'ws-1'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    workstation: WorkstationMeta = Field(
        description="Metadata snapshot describing the workstation",
    )
    last_event_id: UUID | None = Field(
        default=None,
        description="Identifier of the most recent workstation event",
    )
    last_event_type: WorkstationEventType | None = Field(
        default=None,
        description="Type of the most recent workstation event",
    )
    last_event_occurred_at: datetime | None = Field(
        default=None,
        description="Timestamp when the latest workstation event occurred",
    )
    last_event_reason: str | None = Field(
        default=None,
        description="Optional human readable reason associated with the latest event",
    )

    @classmethod
    def from_metadata(cls, metadata: WorkstationMeta) -> "WorkstationRecord":
        """Create a record initialised from standalone workstation metadata.

        Args:
            metadata: Metadata snapshot reported by the runner or discovery
                component.

        Returns:
            WorkstationRecord: Immutable record containing ``metadata`` and no
            associated event information.
        """

        return cls(workstation=metadata)

    def with_metadata(self, metadata: WorkstationMeta) -> "WorkstationRecord":
        """Return a new record with ``metadata`` applied and event data preserved.

        Args:
            metadata: Updated workstation metadata snapshot to persist.

        Returns:
            WorkstationRecord: Copy of the record with the metadata replaced
            while keeping the latest event attributes untouched.
        """

        return self.model_copy(update={"workstation": metadata})

    def with_event(self, event: WorkstationEvent) -> "WorkstationRecord":
        """Return a new record updated with ``event`` details.

        Args:
            event: Workstation event emitted by a runner.

        Returns:
            WorkstationRecord: Copy of the record where both the metadata and
            last event attributes reflect ``event``.
        """

        return self.model_copy(
            update={
                "workstation": event.workstation,
                "last_event_id": event.id,
                "last_event_type": event.type,
                "last_event_occurred_at": event.occurred_at,
                "last_event_reason": event.reason,
            }
        )


class WorkstationUpsertPayload(BaseModel):
    """Request payload for registering or updating workstation metadata.

    Attributes:
        workstation: Metadata snapshot describing the workstation that should
            be stored or replaced in the registry.

    Example:
        >>> WorkstationUpsertPayload(
        ...     workstation=WorkstationMeta(
        ...         id="ws-1",
        ...         fingerprint_id="fp-1",
        ...         state="available",
        ...     )
        ... ).workstation.state
        'available'
    """

    model_config = ConfigDict(extra="forbid")

    workstation: WorkstationMeta = Field(
        description="Metadata snapshot reported by the runner",
    )
