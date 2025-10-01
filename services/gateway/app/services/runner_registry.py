"""In-memory representation of runner metadata."""

from __future__ import annotations

import asyncio
from typing import Iterable

from core import Runner


class RunnerRegistry:
    """Track runner information reported by the discovery layer."""

    def __init__(self, runners: Iterable[Runner] | None = None) -> None:
        """Populate the registry with optional initial runners."""

        self._runners: dict[str, Runner] = {}
        if runners is not None:
            for runner in runners:
                self._runners[runner.id] = runner
        self._lock = asyncio.Lock()

    async def list(self) -> list[Runner]:
        """Return a snapshot of all known runners."""

        async with self._lock:
            return list(self._runners.values())

    async def upsert(self, runner: Runner) -> Runner:
        """Insert or update a runner entry."""

        async with self._lock:
            self._runners[runner.id] = runner
            return runner

    async def get(self, runner_id: str) -> Runner | None:
        """Return a runner by identifier if it is known to the registry."""

        async with self._lock:
            return self._runners.get(runner_id)
