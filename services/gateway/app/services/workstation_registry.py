"""Concurrency-safe registry storing workstation metadata and events."""

from __future__ import annotations

import asyncio

from core import WorkstationEvent, WorkstationMeta, WorkstationState

from ..models.workstations import WorkstationRecord


class WorkstationRegistry:
    """In-memory registry that keeps track of workstation snapshots.

    The registry is designed for lightweight deployments of the gateway where
    workstation metadata can be kept in process memory. Access is guarded by an
    :class:`asyncio.Lock` to guarantee deterministic updates even when multiple
    requests attempt to mutate the same workstation concurrently.

    Attributes:
        _records: Mapping of workstation identifiers to their latest
            :class:`WorkstationRecord` representation.
        _lock: Asynchronous mutex serialising registry operations.
    """

    def __init__(self) -> None:
        """Initialise an empty registry ready to accept workstation records."""

        self._records: dict[str, WorkstationRecord] = {}
        self._lock = asyncio.Lock()

    async def list(self) -> list[WorkstationRecord]:
        """Return all known workstation records in insertion order.

        Returns:
            list[WorkstationRecord]: Copy of the current registry contents. The
            returned list is detached from internal state allowing callers to
            iterate without holding the lock.

        Example:
            >>> registry = WorkstationRegistry()
            >>> await registry.list()
            []
        """

        async with self._lock:
            return list(self._records.values())

    async def get(self, workstation_id: str) -> WorkstationRecord:
        """Return a single workstation record by identifier.

        Args:
            workstation_id: Identifier of the workstation to resolve.

        Returns:
            WorkstationRecord: Snapshot describing the requested workstation.

        Raises:
            KeyError: If the workstation has not been registered yet.
        """

        async with self._lock:
            try:
                return self._records[workstation_id]
            except KeyError as exc:  # pragma: no cover - defensive branch
                raise KeyError("Workstation not found") from exc

    async def upsert_metadata(self, metadata: WorkstationMeta) -> WorkstationRecord:
        """Insert or replace workstation metadata without altering event fields.

        Args:
            metadata: Metadata snapshot to persist in the registry.

        Returns:
            WorkstationRecord: Stored record reflecting ``metadata`` combined
            with any previously observed event attributes.

        Example:
            >>> registry = WorkstationRegistry()
            >>> await registry.upsert_metadata(
            ...     WorkstationMeta(
            ...         id="ws-1",
            ...         fingerprint_id="fp-1",
            ...         state=WorkstationState.AVAILABLE,
            ...     )
            ... )
            WorkstationRecord(...)
        """

        async with self._lock:
            existing = self._records.get(metadata.id)
            record = (
                existing.with_metadata(metadata)
                if existing is not None
                else WorkstationRecord.from_metadata(metadata)
            )
            self._records[metadata.id] = record
            return record

    async def apply_event(self, event: WorkstationEvent) -> WorkstationRecord:
        """Apply ``event`` to the registry and return the updated record.

        Args:
            event: Event payload emitted by a runner describing workstation
                lifecycle changes.

        Returns:
            WorkstationRecord: Updated record including the event metadata and
            last-event bookkeeping fields.

        Example:
            >>> registry = WorkstationRegistry()
            >>> await registry.apply_event(event)  # doctest: +SKIP

        """

        async with self._lock:
            existing = self._records.get(event.workstation.id)
            record = (
                existing.with_event(event)
                if existing is not None
                else WorkstationRecord.from_metadata(event.workstation).with_event(event)
            )
            self._records[event.workstation.id] = record
            return record
