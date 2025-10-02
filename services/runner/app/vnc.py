"""Utilities for managing noVNC helper processes used by the runner."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from asyncio import streams, subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from core.models import SessionVncDetails

from .config import RunnerSettings

LOGGER = logging.getLogger(__name__)


class VncError(RuntimeError):
    """Base exception raised for VNC orchestration failures."""


class VncUnavailableError(VncError):
    """Raised when the environment lacks required noVNC tooling."""


class VncSessionHandle(Protocol):
    """Protocol describing VNC session handles stored by the manager."""

    details: SessionVncDetails

    def browser_environment(self) -> Mapping[str, str]:
        """Return environment variables required for the associated browser."""


class VncController(Protocol):
    """Protocol describing VNC lifecycle controllers."""

    async def allocate(self, session_id: str) -> VncSessionHandle:
        """Provision helper processes and return a handle for ``session_id``."""

    async def release(self, handle: VncSessionHandle | None) -> None:
        """Terminate helper processes associated with ``handle`` if present."""


@dataclass(slots=True, frozen=True)
class _VncSlot:
    """Represents a reserved combination of display and TCP ports."""

    display: int
    vnc_port: int
    ws_port: int


class _VncResourcePool:
    """Maintain a pool of VNC resources safe for concurrent use."""

    def __init__(
        self,
        *,
        displays: Iterable[int],
        vnc_ports: Iterable[int],
        ws_ports: Iterable[int],
    ) -> None:
        self._display_pool = deque(displays)
        self._vnc_ports = deque(vnc_ports)
        self._ws_ports = deque(ws_ports)
        self._active: set[_VncSlot] = set()
        self._lock = asyncio.Lock()

    async def acquire(self) -> _VncSlot:
        """Reserve the next available slot, raising when exhausted."""

        async with self._lock:
            if not self._display_pool or not self._vnc_ports or not self._ws_ports:
                raise VncError("no VNC resources available")
            slot = _VncSlot(
                display=self._display_pool.popleft(),
                vnc_port=self._vnc_ports.popleft(),
                ws_port=self._ws_ports.popleft(),
            )
            self._active.add(slot)
            return slot

    async def release(self, slot: _VncSlot | None) -> None:
        """Return ``slot`` back to the pool if it is currently reserved."""

        if slot is None:
            return
        async with self._lock:
            if slot not in self._active:
                return
            self._active.remove(slot)
            self._display_pool.append(slot.display)
            self._vnc_ports.append(slot.vnc_port)
            self._ws_ports.append(slot.ws_port)


@dataclass(slots=True)
class _ProcessVncSession:
    """Concrete :class:`VncSessionHandle` implementation for subprocesses."""

    slot: _VncSlot
    display: str
    details: SessionVncDetails
    processes: list[subprocess.Process]
    drain_tasks: list[asyncio.Task[None]]
    pool: _VncResourcePool

    def browser_environment(self) -> Mapping[str, str]:
        """Expose environment variables consumed by :mod:`app.browser`."""

        return {"DISPLAY": self.display}

    async def close(self) -> None:
        """Terminate helper processes and return the slot to the pool."""

        try:
            await _terminate_processes(self.processes, self.drain_tasks)
        finally:
            await self.pool.release(self.slot)


class ProcessVncController:
    """Spawn Xvfb/x11vnc/websockify pipelines to back visual sessions."""

    def __init__(self, settings: RunnerSettings) -> None:
        self._settings = settings
        self._pool = _VncResourcePool(
            displays=range(settings.vnc_display_min, settings.vnc_display_max + 1),
            vnc_ports=range(settings.vnc_port_min, settings.vnc_port_max + 1),
            ws_ports=range(settings.vnc_ws_port_min, settings.vnc_ws_port_max + 1),
        )
        self._assets_path = settings.vnc_web_assets_path
        self._check_binaries()

    async def allocate(self, session_id: str) -> _ProcessVncSession:
        """Start helper processes and return a handle for ``session_id``."""

        slot = await self._pool.acquire()
        display = f":{slot.display}"
        processes: list[subprocess.Process] = []
        drain_tasks: list[asyncio.Task[None]] = []
        try:
            xvfb = await self._spawn_process(
                [
                    "Xvfb",
                    display,
                    "-screen",
                    "0",
                    self._settings.vnc_resolution,
                    "+extension",
                    "RANDR",
                    "-nolisten",
                    "tcp",
                ],
                name=f"vnc-xvfb:{slot.display}",
            )
            processes.append(xvfb.process)
            drain_tasks.extend(xvfb.tasks)
            await self._wait_for_display_socket(slot, xvfb.process)

            x11vnc = await self._spawn_process(
                [
                    "x11vnc",
                    "-display",
                    display,
                    "-shared",
                    "-forever",
                    "-rfbport",
                    str(slot.vnc_port),
                    "-localhost",
                    "-nopw",
                    "-quiet",
                ],
                name=f"vnc-x11vnc:{slot.display}",
            )
            processes.append(x11vnc.process)
            drain_tasks.extend(x11vnc.tasks)

            websockify_cmd = ["websockify"]
            assets = self._assets_path
            if assets and assets.is_dir():
                websockify_cmd.append(f"--web={assets}")
            websockify_cmd.extend([
                str(slot.ws_port),
                f"127.0.0.1:{slot.vnc_port}",
            ])
            websockify = await self._spawn_process(
                websockify_cmd,
                name=f"vnc-websockify:{slot.ws_port}",
            )
            processes.append(websockify.process)
            drain_tasks.extend(websockify.tasks)
            await self._wait_for_port("127.0.0.1", slot.ws_port, websockify.process)

            http_url = self._compose_url(
                str(self._settings.vnc_http_base_url),
                slot.ws_port,
                "/vnc.html",
                query_params={"path": "websockify"},
            )
            websocket_url = self._compose_url(
                str(self._settings.vnc_ws_base_url),
                slot.ws_port,
                "/websockify",
            )
            details = SessionVncDetails(
                http_url=http_url,
                websocket_url=websocket_url,
                token=None,
                token_ttl_seconds=None,
            )
            return _ProcessVncSession(
                slot=slot,
                display=display,
                details=details,
                processes=processes,
                drain_tasks=drain_tasks,
                pool=self._pool,
            )
        except Exception:
            await _terminate_processes(processes, drain_tasks)
            await self._pool.release(slot)
            raise

    async def release(self, handle: VncSessionHandle | None) -> None:
        """Best-effort cleanup for a previously allocated session."""

        if handle is None:
            return
        if isinstance(handle, _ProcessVncSession):
            await handle.close()
        else:  # pragma: no cover - defensive branch
            raise TypeError("unsupported VNC handle implementation")

    def _check_binaries(self) -> None:
        """Ensure ``Xvfb``, ``x11vnc`` and ``websockify`` are available."""

        missing = [
            binary
            for binary in ("Xvfb", "x11vnc", "websockify")
            if shutil.which(binary) is None
        ]
        if missing:
            raise VncUnavailableError(
                f"missing required VNC binaries: {', '.join(sorted(missing))}"
            )

    async def _wait_for_display_socket(
        self, slot: _VncSlot, process: subprocess.Process
    ) -> None:
        """Wait until Xvfb exposes its UNIX socket for ``slot``."""

        socket_path = Path("/tmp/.X11-unix") / f"X{slot.display}"
        deadline = asyncio.get_running_loop().time() + self._settings.vnc_startup_timeout_seconds
        while True:
            if socket_path.exists():
                return
            if process.returncode is not None:
                raise VncError(
                    f"Xvfb exited with code {process.returncode} before socket initialisation"
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise VncError(
                    f"timed out waiting for Xvfb display :{slot.display}"
                )
            await asyncio.sleep(0.05)

    async def _wait_for_port(
        self, host: str, port: int, process: subprocess.Process
    ) -> None:
        """Poll ``host:port`` until ``websockify`` starts accepting connections."""

        deadline = asyncio.get_running_loop().time() + self._settings.vnc_startup_timeout_seconds
        while True:
            try:
                reader, writer = await asyncio.open_connection(host, port)
            except OSError:
                if process.returncode is not None:
                    raise VncError(
                        f"websockify exited with code {process.returncode}"
                    )
                if asyncio.get_running_loop().time() >= deadline:
                    raise VncError(
                        f"timed out waiting for websockify on {host}:{port}"
                    )
                await asyncio.sleep(0.1)
            else:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                if reader.at_eof():
                    return
                return

    async def _spawn_process(
        self, args: list[str], *, name: str
    ) -> "_SpawnedProcess":
        """Create a subprocess and drain its standard streams."""

        LOGGER.debug("starting %s with args: %s", name, args)
        process = await subprocess.create_subprocess_exec(
            *args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tasks: list[asyncio.Task[None]] = []
        if process.stdout is not None:
            tasks.append(
                asyncio.create_task(
                    _drain_stream(process.stdout, f"{name}-stdout"),
                    name=f"{name}-stdout",
                )
            )
        if process.stderr is not None:
            tasks.append(
                asyncio.create_task(
                    _drain_stream(process.stderr, f"{name}-stderr"),
                    name=f"{name}-stderr",
                )
            )
        return _SpawnedProcess(process=process, tasks=tasks)

    def _compose_url(
        self,
        base: str,
        port: int,
        path_suffix: str,
        *,
        query_params: dict[str, str] | None = None,
    ) -> str | None:
        """Return a user-facing URL constructed from ``base`` and ``port``."""

        if not base:
            return None
        try:
            parsed = urlparse(base)
        except ValueError:
            LOGGER.warning("invalid VNC base URL: %s", base)
            return None
        hostname = parsed.hostname or parsed.netloc
        if not hostname:
            LOGGER.warning("missing hostname in VNC base URL: %s", base)
            return None
        scheme = parsed.scheme or ("https" if path_suffix.endswith(".html") else "ws")
        if ":" in hostname and not hostname.startswith("["):
            host_part = f"[{hostname}]"
        else:
            host_part = hostname
        port_value = parsed.port if parsed.port is not None else port
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        netloc = f"{userinfo}{host_part}:{port_value}"
        base_path = parsed.path.rstrip("/")
        combined_path = f"{base_path}{path_suffix}" if path_suffix else base_path or "/"
        if not combined_path.startswith("/"):
            combined_path = f"/{combined_path}"
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        if query_params:
            query_items.extend(query_params.items())
        query = urlencode(query_items)
        return urlunparse((scheme, netloc, combined_path, "", query, ""))


@dataclass(slots=True)
class _SpawnedProcess:
    """Represents a subprocess with tasks draining its IO streams."""

    process: subprocess.Process
    tasks: list[asyncio.Task[None]]


async def _drain_stream(stream: streams.StreamReader, name: str) -> None:
    """Consume a subprocess pipe and emit its output to the logger."""

    while True:
        chunk = await stream.readline()
        if not chunk:
            return
        LOGGER.debug("%s: %s", name, chunk.decode(errors="ignore").rstrip())


async def _terminate_processes(
    processes: list[subprocess.Process], tasks: list[asyncio.Task[None]]
) -> None:
    """Terminate helper processes and cancel drain tasks."""

    for process in reversed(processes):
        with contextlib.suppress(Exception):
            if process.returncode is None:
                process.kill()
            await process.wait()
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    processes.clear()
    tasks.clear()


__all__ = [
    "ProcessVncController",
    "VncController",
    "VncError",
    "VncSessionHandle",
    "VncUnavailableError",
]

