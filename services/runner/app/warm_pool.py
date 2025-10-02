"""Warm workstation pool manager for long-lived Camoufox sessions.

The runner keeps a dedicated pool of pre-warmed Camoufox instances so that
interactive workloads can be attached with minimal latency.  The
``WarmPoolManager`` coordinates lifecycle transitions, isolates state between
workstations, and optionally performs a navigation step so that browser tabs
are primed before sessions are assigned.

Example:
    >>> from app.config import RunnerSettings, WarmPoolConfig, WorkstationConfigEntry
    >>> settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
    >>> config = WarmPoolConfig(workstations=[WorkstationConfigEntry(id="ws-1")])
    >>> async def main() -> None:
    ...     manager = WarmPoolManager(settings, warm_pool_config=config)
    ...     await manager.start()
    ...     slot = await manager.reserve_slot()
    ...     await manager.mark_busy(slot.workstation_id)
    ...     await manager.release_slot(slot.workstation_id)
    ...     await manager.drain()
    >>> # asyncio.run(main())  # doctest: +SKIP
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from asyncio import Lock
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .browser import BrowserLaunchError, BrowserSessionHandle, launch_browser
from .config import (
    RunnerSettings,
    WarmPoolConfig,
    WorkstationConfigEntry,
    load_warm_pool_config,
)

__all__ = [
    "WarmPoolError",
    "WarmPoolManager",
    "WarmPoolProvisioningError",
    "WarmPoolSnapshot",
    "WarmPoolState",
    "WarmPoolStateError",
]


LOGGER = logging.getLogger(__name__)


class WarmPoolState(Enum):
    """Finite set of warm pool lifecycle states."""

    IDLE = "idle"
    RESERVED = "reserved"
    BUSY = "busy"
    RECYCLING = "recycling"
    DRAINING = "draining"
    ERROR = "error"


class WarmPoolError(RuntimeError):
    """Base class for warm pool related runtime exceptions."""


class WarmPoolProvisioningError(WarmPoolError):
    """Raised when a workstation cannot be provisioned after retries."""


class WarmPoolStateError(WarmPoolError):
    """Raised when an invalid state transition is attempted."""


@dataclass(slots=True)
class _WarmSlot:
    """Internal representation of a single warm workstation slot."""

    workstation: WorkstationConfigEntry
    fingerprint_id: str | None
    proxy_url: str | None
    prefs_rel_path: str | None
    state: WarmPoolState = WarmPoolState.RECYCLING
    handle: BrowserSessionHandle | None = None
    temp_dir: Path | None = None
    last_error: Exception | None = None
    last_launch_env: dict[str, str] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def snapshot(self) -> "WarmPoolSnapshot":
        """Return a public snapshot of the slot state."""

        return WarmPoolSnapshot(
            workstation_id=self.workstation.id,
            fingerprint_id=self.fingerprint_id,
            proxy_url=self.proxy_url,
            state=self.state,
        )


@dataclass(frozen=True)
class WarmPoolSnapshot:
    """Immutable view of a warm workstation slot used by callers."""

    workstation_id: str
    fingerprint_id: str | None
    proxy_url: str | None
    state: WarmPoolState


class WarmPoolManager:
    """Coordinate lifecycle of pre-warmed Camoufox workstations.

    The manager eagerly provisions Playwright-managed Camoufox instances based
    on the supplied :class:`WarmPoolConfig`.  Each slot maintains its own
    temporary directory, preserves a fingerprint identifier between recycles,
    and exposes explicit state transitions guarded by asyncio locks to remain
    safe for concurrent access.

    Args:
        settings: Runner configuration providing Camoufox binary path, prewarm
            navigation flags, and shared preference location.
        warm_pool_config: Explicit configuration describing workstations.  When
            ``None`` the manager treats warm pool support as disabled.
        config_loader: Optional callable that loads configuration.  Primarily
            useful for tests where configuration is provided via filesystem.
        launcher: Coroutine used to spawn Camoufox processes.  Defaults to
            :func:`launch_browser` with ``browser="camoufox"``.
        navigator: Coroutine responsible for performing optional prewarm
            navigation.  The callable receives ``(slot, handle, start_url)``.
        sleep: Awaitable used for retry backoff and wait windows.
        temp_dir_factory: Callable producing a dedicated temporary directory for
            a workstation.
        max_retries: Maximum number of attempts when provisioning a workstation.
        retry_base_delay: Initial delay (in seconds) used when calculating
            exponential backoff between retries.

    Example:
        >>> settings = RunnerSettings(runner_id="runner", camoufox_path="/usr/bin/camoufox")
        >>> manager = WarmPoolManager(settings)
        >>> # await manager.start()  # doctest: +SKIP
    """

    def __init__(
        self,
        settings: RunnerSettings,
        *,
        warm_pool_config: WarmPoolConfig | None = None,
        config_loader: Callable[[Path | None], WarmPoolConfig | None] = load_warm_pool_config,
        launcher: Callable[..., Awaitable[BrowserSessionHandle]] = launch_browser,
        navigator: Callable[[WarmPoolSnapshot, BrowserSessionHandle, str], Awaitable[None]]
        | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        temp_dir_factory: Callable[[str], Path] | None = None,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._settings = settings
        self._launcher = launcher
        self._navigator = navigator or self._noop_navigate
        self._sleep = sleep
        self._temp_dir_factory = temp_dir_factory or self._default_temp_dir_factory
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._config_loader = config_loader
        self._config = warm_pool_config
        self._slots: dict[str, _WarmSlot] = {}
        self._draining = False

    async def start(self) -> None:
        """Load configuration and provision all workstations in the pool."""

        if self._config is None:
            self._config = self._config_loader(self._settings.warm_pool_config_path)
        if self._config is None or not self._config.workstations:
            LOGGER.info("Warm pool disabled: no configuration entries discovered")
            return

        for entry in self._config.workstations:
            slot = self._build_slot(entry)
            self._slots[entry.id] = slot
            try:
                await self._provision_slot(slot)
                LOGGER.info(
                    "Warm pool slot ready",
                    extra={
                        "workstation_id": entry.id,
                        "fingerprint_id": slot.fingerprint_id,
                        "state": slot.state.value,
                    },
                )
            except WarmPoolProvisioningError:
                LOGGER.exception(
                    "Failed to provision warm pool slot",
                    extra={
                        "workstation_id": entry.id,
                        "fingerprint_id": slot.fingerprint_id,
                    },
                )

    async def reserve_slot(self, workstation_id: str | None = None) -> WarmPoolSnapshot:
        """Move a slot from ``idle`` to ``reserved`` for assignment.

        Args:
            workstation_id: Optional identifier to reserve a specific slot.  When
                omitted the first available idle slot is used.

        Returns:
            WarmPoolSnapshot: Snapshot reflecting the ``reserved`` state.

        Raises:
            WarmPoolStateError: If the pool is draining, no idle slots exist, or
                the requested workstation is not idle.
        """

        if self._draining:
            raise WarmPoolStateError("warm pool is draining")
        slot = self._select_idle_slot(workstation_id)
        async with slot.lock:
            if slot.state is not WarmPoolState.IDLE:
                raise WarmPoolStateError(
                    f"workstation '{slot.workstation.id}' is not idle"
                )
            slot.state = WarmPoolState.RESERVED
            return slot.snapshot()

    async def mark_busy(self, workstation_id: str) -> WarmPoolSnapshot:
        """Transition a ``reserved`` slot into the ``busy`` state."""

        slot = self._require_slot(workstation_id)
        async with slot.lock:
            if slot.state is not WarmPoolState.RESERVED:
                raise WarmPoolStateError(
                    f"workstation '{workstation_id}' is not reserved"
                )
            slot.state = WarmPoolState.BUSY
            return slot.snapshot()

    async def release_slot(self, workstation_id: str) -> WarmPoolSnapshot:
        """Recycle a slot after a busy session finishes."""

        slot = self._require_slot(workstation_id)
        async with slot.lock:
            if slot.state not in {WarmPoolState.BUSY, WarmPoolState.RESERVED}:
                raise WarmPoolStateError(
                    f"workstation '{workstation_id}' cannot be recycled from {slot.state.value}"
                )
            slot.state = WarmPoolState.RECYCLING
            await self._teardown_slot(slot)
            slot.temp_dir = self._temp_dir_factory(slot.workstation.id)
            try:
                await self._provision_slot(slot)
            except WarmPoolProvisioningError:
                LOGGER.exception(
                    "Warm pool slot recycle failed",
                    extra={
                        "workstation_id": slot.workstation.id,
                        "fingerprint_id": slot.fingerprint_id,
                    },
                )
                slot.state = WarmPoolState.ERROR
                raise
            return slot.snapshot()

    async def drain(self) -> list[WarmPoolSnapshot]:
        """Stop accepting new reservations and tear down all slots."""

        self._draining = True
        snapshots: list[WarmPoolSnapshot] = []
        for slot in self._slots.values():
            async with slot.lock:
                slot.state = WarmPoolState.DRAINING
                await self._teardown_slot(slot)
                snapshots.append(slot.snapshot())
        return snapshots

    def list_slots(self) -> list[WarmPoolSnapshot]:
        """Return snapshots for all known slots."""

        return [slot.snapshot() for slot in self._slots.values()]

    def _build_slot(self, entry: WorkstationConfigEntry) -> _WarmSlot:
        """Create an internal representation for ``entry``."""

        fingerprint_id = entry.model_extra.get("fingerprint_id")
        proxy_url = entry.model_extra.get("proxy_url") or entry.model_extra.get("proxy")
        prefs_rel_path = entry.model_extra.get("prefs_rel_path")
        slot = _WarmSlot(
            workstation=entry,
            fingerprint_id=fingerprint_id,
            proxy_url=proxy_url,
            prefs_rel_path=prefs_rel_path,
        )
        slot.temp_dir = self._temp_dir_factory(entry.id)
        return slot

    async def _provision_slot(self, slot: _WarmSlot) -> None:
        """Provision ``slot`` with retry and prewarm handling."""

        try:
            handle = await self._attempt_launch(slot)
        except WarmPoolProvisioningError as exc:
            slot.last_error = exc.__cause__ or exc
            slot.state = WarmPoolState.ERROR
            raise
        else:
            slot.handle = handle
            slot.state = WarmPoolState.IDLE
            slot.last_error = None

    async def _attempt_launch(self, slot: _WarmSlot) -> BrowserSessionHandle:
        """Attempt to launch Camoufox for ``slot`` with retries."""

        delay = self._retry_base_delay
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                handle, env = await self._spawn_browser(slot)
            except Exception as exc:  # pragma: no cover - safety net
                last_error = exc
                LOGGER.exception(
                    "Unhandled error while spawning warm pool slot",
                    extra={
                        "workstation_id": slot.workstation.id,
                        "fingerprint_id": slot.fingerprint_id,
                        "attempt": attempt,
                    },
                )
            else:
                try:
                    await self._maybe_prewarm(slot, handle)
                except Exception as exc:  # pragma: no cover - defensive logging
                    last_error = exc
                    LOGGER.warning(
                        "Prewarm navigation failed",
                        extra={
                            "workstation_id": slot.workstation.id,
                            "fingerprint_id": slot.fingerprint_id,
                            "attempt": attempt,
                        },
                        exc_info=exc,
                    )
                    await self._safe_shutdown(handle)
                else:
                    slot.last_launch_env = env
                    return handle
            if attempt < self._max_retries:
                await self._sleep(delay)
                delay *= 2
        raise WarmPoolProvisioningError(
            f"failed to provision warm workstation '{slot.workstation.id}'"
        ) from last_error

    async def _spawn_browser(self, slot: _WarmSlot) -> tuple[BrowserSessionHandle, dict[str, str]]:
        """Launch Camoufox with slot-specific environment variables."""

        env = self._build_launch_env(slot)
        try:
            handle = await self._launcher(
                self._settings,
                browser="camoufox",
                headless=True,
                env=env,
            )
        except BrowserLaunchError as exc:
            LOGGER.warning(
                "Camoufox launch failed",
                extra={
                    "workstation_id": slot.workstation.id,
                    "fingerprint_id": slot.fingerprint_id,
                },
                exc_info=exc,
            )
            raise
        return handle, env

    async def _maybe_prewarm(
        self, slot: _WarmSlot, handle: BrowserSessionHandle
    ) -> None:
        """Execute optional prewarm navigation against the launched browser."""

        if not self._settings.prewarm_navigation:
            return
        if not self._settings.start_url:
            return
        snapshot = slot.snapshot()
        await self._navigator(snapshot, handle, str(self._settings.start_url))
        wait_seconds = self._settings.start_url_wait_ms / 1000.0
        if wait_seconds > 0:
            await self._sleep(wait_seconds)

    async def _teardown_slot(self, slot: _WarmSlot) -> None:
        """Stop the browser and clean temporary directories."""

        await self._safe_shutdown(slot.handle)
        slot.handle = None
        if slot.temp_dir and slot.temp_dir.exists():
            shutil.rmtree(slot.temp_dir, ignore_errors=True)
        slot.temp_dir = None

    async def _safe_shutdown(self, handle: BrowserSessionHandle | None) -> None:
        """Best-effort shutdown helper used during recycling and drain."""

        if handle is None:
            return
        try:
            await handle.shutdown(force=True)
        except Exception:  # pragma: no cover - defensive logging
            LOGGER.exception("Failed to shutdown warm pool browser cleanly")

    def _build_launch_env(self, slot: _WarmSlot) -> dict[str, str]:
        """Compose environment variables for launching Camoufox."""

        env: dict[str, str] = {
            "CAMOUFOX_HEADLESS": "virtual",
            "CAMOUFOX_WORKSTATION_ID": slot.workstation.id,
        }
        if slot.fingerprint_id:
            env["CAMOUFOX_FINGERPRINT_ID"] = slot.fingerprint_id
        if slot.proxy_url:
            env["CAMOUFOX_PROXY_URL"] = slot.proxy_url
        if slot.prefs_rel_path:
            env["CAMOUFOX_PREFS_REL_PATH"] = slot.prefs_rel_path
        if self._settings.browser_prefs_path is not None:
            env["CAMOUFOX_PREFS_BASE_PATH"] = str(self._settings.browser_prefs_path)
        if slot.temp_dir is None:
            slot.temp_dir = self._temp_dir_factory(slot.workstation.id)
        env["CAMOUFOX_PROFILE_DIR"] = str(slot.temp_dir)
        return env

    def _require_slot(self, workstation_id: str) -> _WarmSlot:
        """Return the slot for ``workstation_id`` or raise an error."""

        try:
            return self._slots[workstation_id]
        except KeyError as exc:  # pragma: no cover - configuration bug
            raise WarmPoolStateError(
                f"unknown workstation '{workstation_id}'"
            ) from exc

    def _select_idle_slot(self, workstation_id: str | None) -> _WarmSlot:
        """Pick an idle slot optionally matching ``workstation_id``."""

        if workstation_id:
            slot = self._require_slot(workstation_id)
            if slot.state is WarmPoolState.IDLE:
                return slot
            raise WarmPoolStateError(
                f"workstation '{workstation_id}' is not idle"
            )
        for slot in self._slots.values():
            if slot.state is WarmPoolState.IDLE:
                return slot
        raise WarmPoolStateError("no idle warm workstations available")

    @staticmethod
    async def _noop_navigate(
        snapshot: WarmPoolSnapshot, handle: BrowserSessionHandle, start_url: str
    ) -> None:
        """Default navigator used when prewarm navigation is disabled."""

        del snapshot, handle, start_url
        return None

    @staticmethod
    def _default_temp_dir_factory(workstation_id: str) -> Path:
        """Allocate a dedicated temporary directory for ``workstation_id``."""

        return Path(tempfile.mkdtemp(prefix=f"warm-pool-{workstation_id}-"))

