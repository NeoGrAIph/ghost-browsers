"""In-memory representation of runner metadata with health-aware selection."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

from core import Runner


class RunnerRegistry:
    """Track runner information reported by the discovery layer.

    The registry stores the most recent :class:`~core.Runner` snapshot for each
    worker and exposes helper APIs tailored for the control plane. Beyond CRUD
    operations it maintains a rotation cursor that enables callers to iterate
    over runners in a round-robin fashion while applying health or capability
    filters. This keeps the gateway scheduling logic straightforward without
    leaking concurrency primitives to the routing layer.
    """

    def __init__(self, runners: Iterable[Runner] | None = None) -> None:
        """Populate the registry with optional initial runners.

        Args:
            runners: Optional collection used to seed the registry. Runners are
                inserted preserving order which later defines the rotation
                sequence for :meth:`select_next`.
        """

        self._runners: dict[str, Runner] = {}
        self._order: list[str] = []
        self._cursor = 0
        if runners is not None:
            for runner in runners:
                self._runners[runner.id] = runner
                self._order.append(runner.id)
        self._lock = asyncio.Lock()

    async def list(self) -> list[Runner]:
        """Return a snapshot of all known runners."""

        async with self._lock:
            return [self._runners[rid] for rid in self._order]

    async def upsert(self, runner: Runner) -> Runner:
        """Insert or update a runner entry.

        Args:
            runner: Runner metadata as provided by the discovery mechanism.

        Returns:
            Runner: The stored runner instance.
        """

        async with self._lock:
            is_new = runner.id not in self._runners
            self._runners[runner.id] = runner
            if is_new:
                self._order.append(runner.id)
            self._cursor = self._cursor % max(len(self._order), 1)
            return runner

    async def get(self, runner_id: str) -> Runner | None:
        """Return a runner by identifier if it is known to the registry."""

        async with self._lock:
            return self._runners.get(runner_id)

    async def select_next(
        self,
        *,
        requires_vnc: bool,
        require_healthy: bool = True,
    ) -> Runner | None:
        """Return the next runner matching capability and health requirements.

        Args:
            requires_vnc: When ``True`` only runners with VNC support are
                considered. This is typically used for interactive sessions.
            require_healthy: When ``True`` (the default) the selector only
                returns runners whose latest health probe succeeded.

        Returns:
            Optional[Runner]: The selected runner or ``None`` if no candidate
            satisfies the requested constraints.
        """

        async with self._lock:
            total = len(self._order)
            if total == 0:
                return None

            start = self._cursor
            for offset in range(total):
                index = (start + offset) % total
                candidate = self._runners[self._order[index]]
                if require_healthy and not candidate.healthy:
                    continue
                if requires_vnc and not candidate.supports_vnc:
                    continue
                self._cursor = (index + 1) % total
                return candidate

            # All runners were filtered out; keep the cursor at the original
            # position so the next caller re-evaluates from the same head.
            self._cursor = start
            return None

    async def record_health(
        self,
        runner_id: str,
        *,
        healthy: bool,
        heartbeat_at: datetime | None,
        total_slots: int | None = None,
        available_slots: int | None = None,
        supports_vnc: bool | None = None,
    ) -> Runner | None:
        """Update the runner snapshot with the latest health probe results.

        Args:
            runner_id: Identifier of the runner being updated.
            healthy: Outcome of the health probe.
            heartbeat_at: Timestamp when the health response was observed.
            total_slots: Optional override for the slot capacity reported by
                the runner.
            available_slots: Optional override for the currently available
                slots derived from the health payload.
            supports_vnc: Optional capability flag indicating whether the
                runner can allocate VNC-enabled sessions.

        Returns:
            Optional[Runner]: The updated runner snapshot or ``None`` if the
            runner is unknown to the registry.
        """

        async with self._lock:
            current = self._runners.get(runner_id)
            if current is None:
                return None

            updates: dict[str, object] = {"healthy": healthy}
            if heartbeat_at is not None:
                updates["last_heartbeat_at"] = heartbeat_at
            if total_slots is not None:
                updates["total_slots"] = total_slots

            if available_slots is not None:
                capacity = (
                    total_slots
                    if total_slots is not None
                    else current.total_slots
                )
                constrained = max(min(available_slots, capacity), 0)
                updates["available_slots"] = constrained

            if supports_vnc is not None:
                updates["supports_vnc"] = supports_vnc

            updated = current.model_copy(update=updates)
            self._runners[runner_id] = updated
            return updated


__all__ = ["RunnerRegistry"]
