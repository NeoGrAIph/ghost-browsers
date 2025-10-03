"""Runner discovery orchestration used by the gateway control plane.

The module implements a pluggable discovery service that periodically retrieves
runner metadata from various backends (static configuration, HTTP endpoints,
etc.) and reconciles the results with the in-memory registries maintained by
the FastAPI application. The entry point is :class:`RunnerDiscoveryService`,
which keeps track of known runner identifiers, updates the
:class:`RunnerRegistry`, and removes stale WebSocket bindings when instances
disappear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence
from uuid import UUID

import anyio
import httpx
from core import Runner, Session

from .runner_registry import RunnerRegistry
from .session_registry import SessionRegistry


class RunnerDiscoveryBackend(Protocol):
    """Protocol implemented by runner discovery data sources.

    Backends are expected to return the full list of active runners on every
    invocation. The service reconciles the snapshot with its local state to
    determine which runners were added, updated, or removed.
    """

    async def discover(self) -> list[Runner]:
        """Return the complete list of active runners."""


@dataclass(slots=True)
class StaticRunnerDiscoveryBackend:
    """Backend that returns runners pre-configured in the settings."""

    runners: Sequence[Runner]

    async def discover(self) -> list[Runner]:
        """Return the configured static runner list."""

        return list(self.runners)


@dataclass(slots=True)
class HttpRunnerDiscoveryBackend:
    """HTTP-based backend retrieving runners from a JSON endpoint."""

    endpoint: str
    timeout: float = 5.0
    transport: httpx.BaseTransport | None = None

    async def discover(self) -> list[Runner]:
        """Fetch the runner catalog via HTTP and parse it into models."""

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.get(self.endpoint)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, list):
            raise ValueError("Runner discovery endpoint must return a JSON array")
        runners: list[Runner] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Runner discovery payload must contain objects")
            runners.append(Runner.model_validate(item))
        return runners


@dataclass(slots=True)
class RunnerSyncResult:
    """Outcome of a discovery reconciliation iteration."""

    added: set[str]
    updated: set[str]
    removed: set[str]


class RunnerDiscoveryService:
    """High-level facade coordinating runner discovery and reconciliation.

    The service keeps track of known runner identifiers, updates the
    :class:`RunnerRegistry`, and ensures WebSocket bindings belonging to stale
    runners are removed to prevent gateway clients from connecting to dangling
    endpoints.
    """

    def __init__(
        self,
        *,
        settings,
        runner_registry: RunnerRegistry,
        session_registry: SessionRegistry | None = None,
        backend: RunnerDiscoveryBackend | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Initialise the service with the configured discovery backend.

        Args:
            settings: :class:`~app.config.GatewaySettings` instance that defines
                the discovery mode and optional HTTP endpoint.
            runner_registry: Registry that should be updated with discovery
                results.
            session_registry: Optional session registry used when dropping WebSocket
                bindings for stale runners.
            backend: Optional backend override; useful in tests.
            transport: Optional HTTP transport injected into HTTP-based
                backends (primarily for unit tests with ``MockTransport``).
        """

        from app.config import GatewaySettings  # Local import to avoid cycles

        if not isinstance(settings, GatewaySettings):  # pragma: no cover - defensive
            raise TypeError("settings must be an instance of GatewaySettings")

        self._settings = settings
        self._runner_registry = runner_registry
        self._session_registry = session_registry
        self._transport = transport
        self._backend = backend or self._build_backend()
        self._known_runner_ids: set[str] = set()
        self._lock = anyio.Lock()

    async def refresh(self) -> RunnerSyncResult:
        """Synchronise the registry with the latest discovery snapshot.

        Returns:
            RunnerSyncResult: Dataclass describing the reconciliation outcome.
        """

        async with self._lock:
            runners = await self._backend.discover()
            observed_ids: set[str] = set()
            added: set[str] = set()
            updated: set[str] = set()

            for runner in runners:
                observed_ids.add(runner.id)
                if runner.id in self._known_runner_ids:
                    updated.add(runner.id)
                else:
                    added.add(runner.id)
                await self._runner_registry.upsert(runner)

            removed = self._known_runner_ids - observed_ids
            self._known_runner_ids = observed_ids

        if removed:
            await self._handle_removed_runners(removed)

        return RunnerSyncResult(added=added, updated=updated, removed=removed)

    async def _handle_removed_runners(self, removed: set[str]) -> None:
        """Remove stale runners and drop WebSocket bindings.

        Args:
            removed: Set of runner identifiers that disappeared from discovery.
        """

        sessions = await self._sessions_for_runners(removed)
        for session in sessions:
            await self._runner_registry.drop_session_ws_endpoint(session.id)
        for runner_id in removed:
            await self._runner_registry.remove(runner_id)

    async def _sessions_for_runners(self, runner_ids: Iterable[str]) -> list[Session]:
        """Return sessions associated with the provided ``runner_ids``."""

        if self._session_registry is None:
            return []
        sessions = await self._session_registry.list()
        return [session for session in sessions if session.runner_id in runner_ids]

    def _build_backend(self) -> RunnerDiscoveryBackend:
        """Create a discovery backend based on the configured mode."""

        mode = self._settings.discovery_mode.lower()
        if mode == "static":
            return StaticRunnerDiscoveryBackend(self._settings.runners)
        if mode == "http":
            if not self._settings.discovery_endpoint:
                raise ValueError("DISCOVERY_ENDPOINT must be set for http discovery")
            return HttpRunnerDiscoveryBackend(
                endpoint=self._settings.discovery_endpoint,
                transport=self._transport,
            )
        raise ValueError(f"Unsupported discovery_mode: {self._settings.discovery_mode}")


async def purge_sessions_for_missing_runners(
    session_registry: SessionRegistry,
    runner_registry: RunnerRegistry,
    missing_runner_ids: Iterable[str],
) -> list[UUID]:
    """Delete sessions whose runners disappeared and drop WS bindings.

    Args:
        session_registry: Registry storing active sessions.
        runner_registry: Runner registry exposing WebSocket binding helpers.
        missing_runner_ids: Identifiers of runners that vanished from discovery.

    Returns:
        list[UUID]: Identifiers of sessions removed from the registry.
    """

    removed_ids = {runner_id for runner_id in missing_runner_ids}
    if not removed_ids:
        return []

    sessions = await session_registry.list()
    removed_sessions: list[UUID] = []
    for session in sessions:
        if session.runner_id in removed_ids:
            try:
                await session_registry.delete(session.id)
            except KeyError:
                pass
            else:
                removed_sessions.append(session.id)
            try:
                await runner_registry.drop_session_ws_endpoint(session.id)
            except KeyError:
                pass
    return removed_sessions


__all__ = [
    "RunnerDiscoveryBackend",
    "StaticRunnerDiscoveryBackend",
    "HttpRunnerDiscoveryBackend",
    "RunnerSyncResult",
    "RunnerDiscoveryService",
    "purge_sessions_for_missing_runners",
]
