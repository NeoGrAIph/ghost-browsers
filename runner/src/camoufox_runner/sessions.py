"""Session orchestration logic used by the Camoufox runner."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from asyncio import subprocess as aio_subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from camoufox import launch_options
from playwright._impl._driver import compute_driver_executable
from playwright.async_api import Playwright

from .config import RunnerSettings
from .models import SessionDetail, SessionStatus, SessionSummary
from .url_utils import navigable_start_url

LOGGER = logging.getLogger(__name__)

BROWSER_SERVER_LAUNCH_TIMEOUT = 45


@dataclass(slots=True, frozen=True)
class VncSlot:
    """Tracks the numeric resources reserved for a VNC session."""

    display: int
    vnc_port: int
    ws_port: int


@dataclass(slots=True)
class VncSession:
    """Runtime information about a VNC session and its helper processes."""

    slot: VncSlot
    display: str
    http_url: str | None
    ws_url: str | None
    processes: list[aio_subprocess.Process]
    drain_tasks: list[asyncio.Task[None]] = field(default_factory=list)


class VNCUnavailableError(RuntimeError):
    """Raised when VNC-specific operations are requested but tooling is absent."""


@dataclass(slots=True)
class _Prewarmed:
    """Container holding a prewarmed browser server and optional VNC session."""

    server: "_SubprocessBrowserServer"
    vnc_session: VncSession | None
    headless: bool


class VncResourcePool:
    """Manage allocation of DISPLAY numbers and ports for VNC sessions."""

    def __init__(self, *, displays: Iterable[int], vnc_ports: Iterable[int], ws_ports: Iterable[int]) -> None:
        # ``deque`` gives us efficient pop/append operations from both ends which
        # is perfect for a pool allocator.
        self._display_pool = deque(displays)
        self._vnc_ports = deque(vnc_ports)
        self._ws_ports = deque(ws_ports)
        self._active: set[VncSlot] = set()
        self._lock = asyncio.Lock()

    async def acquire(self) -> VncSlot:
        """Reserve a display/port triple for a VNC session."""

        async with self._lock:
            if not self._display_pool or not self._vnc_ports or not self._ws_ports:
                raise RuntimeError("No available VNC slots")
            slot = VncSlot(
                display=self._display_pool.popleft(),
                vnc_port=self._vnc_ports.popleft(),
                ws_port=self._ws_ports.popleft(),
            )
            self._active.add(slot)
            return slot

    async def release(self, slot: VncSlot | None) -> None:
        """Return a slot back to the pool."""

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
class SessionHandle:
    """In-memory representation of a running Camoufox session."""

    id: str
    headless: bool
    idle_ttl_seconds: int
    created_at: datetime
    last_seen_at: datetime
    server: "_SubprocessBrowserServer"
    vnc: bool
    start_url: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    status: SessionStatus = SessionStatus.INIT
    controller_browser: Any | None = None
    controller_context: Any | None = None
    controller_page: Any | None = None
    vnc_session: VncSession | None = field(default=None, repr=False)
    start_url_wait: str = "load"

    def summary(self) -> SessionSummary:
        """Return a lightweight model suitable for list responses."""

        return SessionSummary(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            last_seen_at=self.last_seen_at,
            headless=self.headless,
            idle_ttl_seconds=self.idle_ttl_seconds,
            labels=self.labels,
            vnc=self.vnc,
            start_url_wait=self.start_url_wait,
        )

    def detail(self, ws_endpoint: str, vnc_payload: dict[str, Any]) -> SessionDetail:
        """Combine summary information with connection metadata."""

        return SessionDetail(
            **self.summary().model_dump(),
            ws_endpoint=ws_endpoint,
            vnc_info=vnc_payload,
        )


class SessionManager:
    """Coordinate Playwright browser servers and optional VNC sidecars."""

    def __init__(self, settings: RunnerSettings, playwright: Playwright) -> None:
        self._settings = settings
        self._playwright = playwright
        self._sessions: dict[str, SessionHandle] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None
        self._prewarm_task: asyncio.Task[None] | None = None
        self._vnc_pool = VncResourcePool(
            displays=range(settings.vnc_display_min, settings.vnc_display_max + 1),
            vnc_ports=range(settings.vnc_port_min, settings.vnc_port_max + 1),
            ws_ports=range(settings.vnc_ws_port_min, settings.vnc_ws_port_max + 1),
        )
        # Prewarmed resources ready to be claimed for faster session creation.
        self._prewarm_headless: list[_Prewarmed] = []
        self._prewarm_vnc: list[_Prewarmed] = []
        self._vnc_available = all(shutil.which(cmd) for cmd in ("Xvfb", "x11vnc", "websockify"))
        if not self._vnc_available and settings.prewarm_vnc > 0:
            LOGGER.info("VNC tooling not available; disabling VNC prewarm")
        self._prewarm_headless_target = settings.prewarm_headless
        self._prewarm_vnc_target = settings.prewarm_vnc if self._vnc_available else 0
        self._start_url_wait = settings.start_url_wait
        # Track in-flight bootstrap tasks so they can be cancelled during shutdown.
        self._bootstrap_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Start background maintenance tasks."""

        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="camoufox-cleanup")
        # Start prewarming loop if targets are non-zero.
        if self._prewarm_headless_target > 0 or self._prewarm_vnc_target > 0:
            self._prewarm_task = asyncio.create_task(self._prewarm_loop(), name="camoufox-prewarm")

    async def disable_http3(self) -> None:
        """Force future sessions to launch with HTTP/3 disabled."""

        if getattr(self._settings, "disable_http3", False):
            return
        LOGGER.warning("HTTP/3 support is unavailable — draining prewarmed sessions and disabling it")
        setattr(self._settings, "disable_http3", True)
        await self._close_prewarmed()

    async def close(self) -> None:
        """Stop background tasks and shut down all sessions."""

        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        if self._prewarm_task:
            self._prewarm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prewarm_task
        if self._bootstrap_tasks:
            tasks = list(self._bootstrap_tasks)
            self._bootstrap_tasks.clear()
            for task in tasks:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        await self._close_prewarmed()
        await self._close_all()

    async def _close_all(self) -> None:
        """Terminate all active sessions."""

        async with self._lock:
            handles = list(self._sessions.values())
            self._sessions.clear()
        for handle in handles:
            await self._shutdown_handle(handle)

    async def _close_prewarmed(self) -> None:
        """Drain and close all prewarmed resources."""

        async with self._lock:
            headless = list(self._prewarm_headless)
            vnc = list(self._prewarm_vnc)
            self._prewarm_headless.clear()
            self._prewarm_vnc.clear()
        for item in headless + vnc:
            try:
                await item.server.close()
            finally:
                await self._stop_vnc_session(item.vnc_session)

    async def list_summaries(self) -> list[SessionSummary]:
        """Return lightweight information about each session."""

        async with self._lock:
            return [handle.summary() for handle in self._sessions.values()]

    async def list_details(self) -> list[SessionDetail]:
        """Return detailed information about each session."""

        async with self._lock:
            handles = list(self._sessions.values())
        return [self.detail_for(handle) for handle in handles]

    async def get(self, session_id: str) -> SessionHandle | None:
        """Retrieve a session handle by identifier."""

        async with self._lock:
            return self._sessions.get(session_id)

    async def create(self, payload: dict[str, Any]) -> SessionHandle:
        """Create a new session using optional prewarmed resources."""

        defaults = self._settings.session_defaults
        headless = payload.get("headless")
        if headless is None:
            headless = defaults.headless
        vnc_enabled = bool(payload.get("vnc", False))
        vnc_session: VncSession | None = None
        if vnc_enabled:
            headless = False
            if not self._vnc_available:
                raise VNCUnavailableError("VNC is not supported on this runner")
        # Try to acquire a prewarmed resource to avoid cold starts
        prewarmed = await self._acquire_prewarmed(vnc=vnc_enabled, headless=headless)
        idle_ttl = payload.get("idle_ttl_seconds") or defaults.idle_ttl_seconds
        labels = payload.get("labels") or {}
        start_url = payload.get("start_url") or defaults.start_url
        wait_override = payload.get("start_url_wait")
        if wait_override in {"none", "domcontentloaded", "load"}:
            start_url_wait = wait_override
        else:
            start_url_wait = self._start_url_wait

        try:
            if prewarmed is not None:
                server = prewarmed.server
                vnc_session = prewarmed.vnc_session
            else:
                if vnc_enabled:
                    vnc_session = await self._start_vnc_session()
                server = await self._launch_browser_server(
                    headless=headless,
                    vnc=vnc_enabled,
                    display=vnc_session.display if vnc_session else None,
                )
        except Exception:
            await self._stop_vnc_session(vnc_session)
            raise
        created_at = datetime.now(tz=timezone.utc)
        handle = SessionHandle(
            id=str(uuid.uuid4()),
            headless=headless,
            idle_ttl_seconds=idle_ttl,
            created_at=created_at,
            last_seen_at=created_at,
            server=server,
            vnc=vnc_enabled,
            start_url=start_url,
            labels=labels,
            status=SessionStatus.READY,
            vnc_session=vnc_session,
            start_url_wait=start_url_wait,
        )
        self._schedule_bootstrap(handle)
        async with self._lock:
            self._sessions[handle.id] = handle
        # Trigger background prewarm top-up (best-effort)
            asyncio.create_task(self._top_up_once(), name="camoufox-prewarm-kick").add_done_callback(lambda _: None)
        return handle

    async def delete(self, session_id: str) -> SessionHandle | None:
        """Remove a session and shut down its processes."""

        async with self._lock:
            handle = self._sessions.pop(session_id, None)
        if handle:
            handle.status = SessionStatus.TERMINATING
            await self._shutdown_handle(handle)
        return handle

    async def touch(self, session_id: str) -> SessionHandle | None:
        """Update ``last_seen_at`` to keep a session alive."""

        async with self._lock:
            handle = self._sessions.get(session_id)
            if not handle:
                return None
            handle.last_seen_at = datetime.now(tz=timezone.utc)
            return handle

    async def _cleanup_loop(self) -> None:
        """Periodic task that cleans up stale sessions."""

        while True:
            await asyncio.sleep(self._settings.cleanup_interval)
            await self._cleanup_expired()

    async def _cleanup_expired(self) -> None:
        """Remove sessions that have exceeded their idle timeout."""

        now = time.time()
        stale: list[SessionHandle] = []
        async with self._lock:
            for handle in list(self._sessions.values()):
                ttl_deadline = handle.last_seen_at.timestamp() + handle.idle_ttl_seconds
                if now >= ttl_deadline:
                    handle.status = SessionStatus.TERMINATING
                    stale.append(handle)
                    self._sessions.pop(handle.id, None)
        for handle in stale:
            LOGGER.info("Session %s expired — shutting down", handle.id)
            await self._shutdown_handle(handle)

    async def _shutdown_handle(self, handle: SessionHandle) -> None:
        """Tear down browser/VNC processes associated with a handle."""

        await self._teardown_controller(handle)
        try:
            await handle.server.close()
        finally:
            await self._stop_vnc_session(handle.vnc_session)
            handle.vnc_session = None
            handle.status = SessionStatus.DEAD

    async def _bootstrap_session(self, handle: SessionHandle) -> None:
        """Open the configured start URL to warm up the browser session."""

        if not handle.start_url:
            return
        if handle.start_url_wait == "none":
            return
        try:
            browser = await self._playwright.firefox.connect(handle.server.ws_endpoint)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(
                navigable_start_url(handle.start_url),
                wait_until=handle.start_url_wait,
            )
            handle.controller_browser = browser
            handle.controller_context = context
            handle.controller_page = page
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to open %s in session %s: %s", handle.start_url, handle.id, exc)

    async def _teardown_controller(self, handle: SessionHandle) -> None:
        """Close Playwright controller objects associated with a session."""

        if handle.controller_page:
            with contextlib.suppress(Exception):
                await handle.controller_page.close()
            handle.controller_page = None
        if handle.controller_context:
            with contextlib.suppress(Exception):
                await handle.controller_context.close()
            handle.controller_context = None
        if handle.controller_browser:
            with contextlib.suppress(Exception):
                await handle.controller_browser.close()
            handle.controller_browser = None

    async def iter_details(self):
        """Asynchronously iterate over session details without holding the lock."""

        async with self._lock:
            handles = list(self._sessions.values())
        for handle in handles:
            yield self.detail_for(handle)

    def ws_endpoint_for(self, handle: SessionHandle) -> str:
        """Return the Playwright WebSocket endpoint for a session."""

        return handle.server.ws_endpoint

    def detail_for(self, handle: SessionHandle) -> SessionDetail:
        """Construct a :class:`SessionDetail` model for the given handle."""

        return handle.detail(
            self.ws_endpoint_for(handle),
            self._build_vnc_payload(handle),
        )

    async def _acquire_prewarmed(self, *, vnc: bool, headless: bool) -> _Prewarmed | None:
        """Return a prewarmed browser server if one is available."""

        async with self._lock:
            if vnc and self._prewarm_vnc:
                return self._prewarm_vnc.pop()
            if (not vnc) and headless and self._prewarm_headless:
                return self._prewarm_headless.pop()
            return None

    async def _prewarm_loop(self) -> None:
        """Periodically ensure we have the configured number of prewarmed resources."""

        interval = self._settings.prewarm_check_interval_seconds
        while True:
            try:
                await self._top_up_once()
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Prewarm loop error: %s", exc)
            await asyncio.sleep(interval)

    async def _top_up_once(self) -> None:
        """Top up headless and VNC prewarm pools to their targets."""

        target_headless = self._prewarm_headless_target
        target_vnc = self._prewarm_vnc_target if self._vnc_available else 0
        async with self._lock:
            need_headless = max(0, target_headless - len(self._prewarm_headless))
            need_vnc = max(0, target_vnc - len(self._prewarm_vnc))
        for _ in range(need_headless):
            try:
                server = await self._launch_browser_server(headless=True, vnc=False, display=None)
                item = _Prewarmed(server=server, vnc_session=None, headless=True)
                async with self._lock:
                    self._prewarm_headless.append(item)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Failed to prewarm headless server: %s", exc)
                break
        for _ in range(need_vnc):
            vnc_session: VncSession | None = None
            try:
                vnc_session = await self._start_vnc_session()
                server = await self._launch_browser_server(headless=False, vnc=True, display=vnc_session.display)
                item = _Prewarmed(server=server, vnc_session=vnc_session, headless=False)
                async with self._lock:
                    self._prewarm_vnc.append(item)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Failed to prewarm VNC server: %s", exc)
                # release possibly opened VNC session if server launch failed
                if vnc_session is not None:
                    with contextlib.suppress(Exception):
                        await self._stop_vnc_session(vnc_session)
                break

    def _build_vnc_payload(self, handle: SessionHandle) -> dict[str, Any]:
        """Generate the VNC section of the session detail payload."""

        if not handle.vnc or not handle.vnc_session:
            return {"ws": None, "http": None, "password_protected": False}
        return {
            "ws": handle.vnc_session.ws_url,
            "http": handle.vnc_session.http_url,
            "password_protected": False,
        }

    def _schedule_bootstrap(self, handle: SessionHandle) -> None:
        """Fire and forget the optional start URL preloading task."""

        if not handle.start_url:
            return
        if handle.start_url_wait == "none":
            return

        task = asyncio.create_task(
            self._bootstrap_session(handle),
            name=f"camoufox-bootstrap:{handle.id}",
        )
        self._bootstrap_tasks.add(task)

        def _cleanup(_: asyncio.Future[Any]) -> None:
            self._bootstrap_tasks.discard(task)

        task.add_done_callback(_cleanup)

    async def _start_vnc_session(self) -> VncSession:
        """Launch Xvfb, x11vnc and websockify for a new session."""

        if not self._vnc_available:
            raise VNCUnavailableError("VNC is not supported on this runner")
        slot = await self._vnc_pool.acquire()
        display_name = f":{slot.display}"
        processes: list[aio_subprocess.Process] = []
        drain_tasks: list[asyncio.Task[None]] = []
        assets_path = self._settings.vnc_web_assets_path
        try:
            LOGGER.debug(
                "Allocating VNC slot display=%s vnc_port=%s ws_port=%s",
                display_name,
                slot.vnc_port,
                slot.ws_port,
            )
            xvfb_proc, xvfb_tasks = await self._spawn_process(
                [
                    "Xvfb",
                    display_name,
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
            processes.append(xvfb_proc)
            drain_tasks.extend(xvfb_tasks)
            await self._wait_for_display_socket(slot, xvfb_proc)

            x11vnc_cmd = [
                "x11vnc",
                "-display",
                display_name,
                "-shared",
                "-forever",
                "-rfbport",
                str(slot.vnc_port),
                "-localhost",
                "-nopw",
                "-quiet",
            ]
            x11vnc_proc, x11vnc_tasks = await self._spawn_process(
                x11vnc_cmd,
                name=f"vnc-x11vnc:{slot.display}",
            )
            processes.append(x11vnc_proc)
            drain_tasks.extend(x11vnc_tasks)

            websockify_cmd: list[str] = ["websockify"]
            if assets_path and os.path.isdir(assets_path):
                websockify_cmd.append(f"--web={assets_path}")
            websockify_cmd.extend([
                str(slot.ws_port),
                f"127.0.0.1:{slot.vnc_port}",
            ])
            websockify_proc, websockify_tasks = await self._spawn_process(
                websockify_cmd,
                name=f"vnc-websockify:{slot.ws_port}",
            )
            processes.append(websockify_proc)
            drain_tasks.extend(websockify_tasks)
            await self._wait_for_port("127.0.0.1", slot.ws_port, websockify_proc)

            http_url = self._compose_public_url(
                self._settings.vnc_http_base,
                slot.ws_port,
                "/vnc.html",
                query_params={"path": "websockify"},
            )
            ws_url = self._compose_public_url(
                self._settings.vnc_ws_base,
                slot.ws_port,
                "/websockify",
            )

            return VncSession(
                slot=slot,
                display=display_name,
                http_url=http_url,
                ws_url=ws_url,
                processes=processes,
                drain_tasks=drain_tasks,
            )
        except Exception:
            await self._terminate_vnc_processes(processes, drain_tasks)
            await self._vnc_pool.release(slot)
            raise

    async def _stop_vnc_session(self, session: VncSession | None) -> None:
        """Terminate helper processes and return the slot to the pool."""

        if not session:
            return
        try:
            await self._terminate_vnc_processes(session.processes, session.drain_tasks)
        finally:
            await self._vnc_pool.release(session.slot)

    async def _terminate_vnc_processes(
        self,
        processes: list[aio_subprocess.Process],
        drain_tasks: list[asyncio.Task[None]],
    ) -> None:
        """Kill helper processes and cancel drain tasks safely."""

        for process in reversed(processes):
            with contextlib.suppress(Exception):
                await _terminate_process(process, kill=True)
        for task in drain_tasks:
            task.cancel()
        for task in drain_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        processes.clear()
        drain_tasks.clear()

    def _compose_public_url(
        self,
        base: str | None,
        port: int,
        path_suffix: str,
        *,
        query_params: dict[str, str] | None = None,
    ) -> str | None:
        """Build an externally reachable URL for VNC clients."""

        if not base:
            return None
        try:
            parsed = urlparse(base)
        except ValueError:
            LOGGER.warning("Invalid VNC base URL: %s", base)
            return None
        scheme = parsed.scheme or ("https" if path_suffix.endswith(".html") else "ws")
        hostname = parsed.hostname or parsed.netloc
        if not hostname:
            LOGGER.warning("Unable to determine hostname for VNC base URL: %s", base)
            return None
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        if ":" in hostname and not hostname.startswith("["):
            host_part = f"[{hostname}]"
        else:
            host_part = hostname
        override_port = None
        if parsed.port is not None:
            if parsed.path and parsed.path != "/":
                override_port = parsed.port
            elif parsed.query:
                override_port = parsed.port
        if override_port is not None:
            netloc = f"{userinfo}{host_part}:{override_port}"
        else:
            netloc = f"{userinfo}{host_part}:{port}"
        base_path = parsed.path.rstrip("/")
        combined_path = f"{base_path}{path_suffix}" if path_suffix else base_path or "/"
        if not combined_path.startswith("/"):
            combined_path = f"/{combined_path}"
        query_items = parse_qsl(parsed.query, keep_blank_values=True)
        adjusted_query_params = dict(query_params) if query_params else None
        if adjusted_query_params and "path" in adjusted_query_params:
            base_segment = base_path.lstrip("/")
            if base_segment:
                raw_path = adjusted_query_params["path"]
                path_value = raw_path.lstrip("/")
                needs_prefix = not (
                    path_value == base_segment
                    or path_value.startswith(f"{base_segment}/")
                )
                if needs_prefix:
                    if path_value:
                        adjusted_query_params["path"] = f"{base_segment}/{path_value}"
                    else:
                        adjusted_query_params["path"] = base_segment
                else:
                    # Normalise to a relative form for consistency with noVNC expectations.
                    adjusted_query_params["path"] = path_value
        if adjusted_query_params:
            query_items.extend(adjusted_query_params.items())
        if not any(key == "target_port" for key, _ in query_items):
            query_items.append(("target_port", str(port)))
        query = urlencode(query_items)
        return urlunparse((scheme, netloc, combined_path, "", query, ""))

    async def _wait_for_display_socket(self, slot: VncSlot, process: aio_subprocess.Process) -> None:
        """Wait until Xvfb creates its UNIX socket."""

        socket_path = f"/tmp/.X11-unix/X{slot.display}"
        deadline = asyncio.get_running_loop().time() + self._settings.vnc_startup_timeout_seconds
        while True:
            if os.path.exists(socket_path):
                return
            if process.returncode is not None:
                raise RuntimeError(f"Xvfb exited with code {process.returncode}")
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(f"Timed out waiting for Xvfb display {slot.display}")
            await asyncio.sleep(0.05)

    async def _wait_for_port(
        self,
        host: str,
        port: int,
        process: aio_subprocess.Process,
    ) -> None:
        """Wait until a TCP port starts accepting connections."""

        deadline = asyncio.get_running_loop().time() + self._settings.vnc_startup_timeout_seconds
        while True:
            try:
                reader, writer = await asyncio.open_connection(host, port)
            except OSError:
                if process.returncode is not None:
                    raise RuntimeError(f"websockify exited with code {process.returncode}")
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError(f"Timed out waiting for websockify on {host}:{port}")
                await asyncio.sleep(0.1)
                continue
            else:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                return

    async def _spawn_process(
        self,
        args: list[str],
        *,
        name: str,
        env: dict[str, str] | None = None,
    ) -> tuple[aio_subprocess.Process, list[asyncio.Task[None]]]:
        """Start a helper process and stream its output to the logs."""

        LOGGER.debug("Starting %s with args: %s", name, args)
        process = await aio_subprocess.create_subprocess_exec(
            *args,
            stdout=aio_subprocess.PIPE,
            stderr=aio_subprocess.PIPE,
            env=env,
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
        return process, tasks

    async def _launch_browser_server(
        self,
        *,
        headless: bool,
        vnc: bool,
        display: str | None,
    ) -> "_SubprocessBrowserServer":
        """Spawn a Camoufox Playwright server for a session."""

        opts = launch_options(headless=headless)
        firefox_prefs = opts.setdefault("firefox_user_prefs", {})
        if self._settings.disable_ipv6:
            firefox_prefs["network.dns.disableIPv6"] = True
        if self._settings.disable_http3:
            # Additional toggles to handle older preference aliases that may be
            # present in various Firefox builds bundled with Playwright.
            firefox_prefs["network.http.http3.enabled"] = False
            firefox_prefs["network.http.http3.enable"] = False
            firefox_prefs["network.http.http3.enable_0rtt"] = False
            # ``enable_alt_svc`` controls whether HTTP/3 Alt-Svc upgrades are
            # attempted for origins that advertise QUIC support.  Some Firefox
            # builds still use the legacy ``alt_svc`` preference so keep both
            # toggles in sync to cover older versions shipped with Playwright.
            firefox_prefs["network.http.http3.enable_alt_svc"] = False
            firefox_prefs["network.http.http3.alt_svc"] = False
            firefox_prefs["network.http.http3.retry_different_host"] = False
            firefox_prefs["network.dns.http3_echconfig.enabled"] = False
            # Firefox 127+ can promote HTTPS RR (SVCB) DNS responses to HTTP/3
            # connections even when Alt-Svc is disabled.  In isolated
            # environments the UDP handshake for the QUIC endpoint never
            # completes which ultimately bubbles up as ``PR_END_OF_FILE_ERROR``
            # inside the VNC session.  Disabling the HTTPS RR promotion keeps
            # the resolver on the HTTP/2 code paths for Cloudflare-backed
            # targets such as ``https://bot.sannysoft.com``.
            firefox_prefs["network.dns.use_https_rr_as_altsvc"] = False
            # Cloudflare-backed targets such as ``https://bot.sannysoft.com``
            # publish Alt-Svc hints that point to HTTP/3-only backends.  Even
            # with the HTTP/3-specific preferences disabled Firefox can cache
            # the Alt-Svc entry in ``SiteSecurityServiceState.bin`` and reuse it
            # for subsequent navigations within the same persistent profile. In
            # restricted environments (no UDP/QUIC) this manifests as the
            # ``PR_END_OF_FILE_ERROR`` the cluster observes after the very
            # first successful visit.  Disabling Alt-Svc at the global layer
            # prevents Firefox from storing those hints in the first place.
            firefox_prefs["network.http.altsvc.enabled"] = False
            firefox_prefs["network.http.altsvc.https"] = False
        if self._settings.disable_webrtc:
            firefox_prefs["media.peerconnection.enabled"] = False
        env_vars = {k: v for k, v in (opts.get("env") or {}).items() if v is not None}
        if self._settings.disable_http3:
            # ``MOZ_DISABLE_HTTP3`` short-circuits the networking stack before
            # any profile is created which guarantees that child processes such
            # as the preloaded content process inherit the setting.
            env_vars["MOZ_DISABLE_HTTP3"] = "1"
        if display:
            env_vars["DISPLAY"] = display
        profile_dir = tempfile.mkdtemp(prefix="camoufox-profile-")

        config: dict[str, Any] = {
            "headless": headless,
            "args": opts.get("args") or [],
            "env": env_vars,
        }
        # Persist the browser context between launches to speed up repeated
        # connections from the same worker process.
        config["persistentContext"] = True
        config["userDataDir"] = profile_dir
        if executable_path := opts.get("executable_path"):
            config["executablePath"] = executable_path
        if prefs := opts.get("firefox_user_prefs"):
            config["firefoxUserPrefs"] = prefs
        if proxy := opts.get("proxy"):
            config["proxy"] = proxy
        if opts.get("ignore_default_args") is not None:
            config["ignoreDefaultArgs"] = opts["ignore_default_args"]
        node_path, cli_path = compute_driver_executable()

        config_path = await asyncio.to_thread(_write_launch_config, config)
        process = await aio_subprocess.create_subprocess_exec(
            node_path,
            cli_path,
            "launch-server",
            "--browser=firefox",
            f"--config={config_path}",
            stdout=aio_subprocess.PIPE,
            stderr=aio_subprocess.PIPE,
        )

        try:
            try:
                raw_endpoint = await asyncio.wait_for(
                    process.stdout.readline(), timeout=BROWSER_SERVER_LAUNCH_TIMEOUT
                )
            except asyncio.TimeoutError as exc:
                await _terminate_process(process)
                raise RuntimeError("Timed out launching Camoufox server") from exc

            if not raw_endpoint:
                stderr_output = await process.stderr.read()
                return_code = await process.wait()
                message = stderr_output.decode().strip() or "unknown error"
                raise RuntimeError(
                    f"Failed to launch Camoufox server (code {return_code}): {message}"
                )

            ws_endpoint = raw_endpoint.decode().strip()
            stdout_task = asyncio.create_task(
                _drain_stream(process.stdout, "camoufox-stdout"),
                name="camoufox-server-stdout",
            )
            stderr_task = asyncio.create_task(
                _drain_stream(process.stderr, "camoufox-stderr"),
                name="camoufox-server-stderr",
            )
            return _SubprocessBrowserServer(
                process,
                ws_endpoint,
                [stdout_task, stderr_task],
                profile_dir,
            )
        except Exception:
            await _terminate_process(process, kill=True)
            await asyncio.to_thread(_remove_directory, profile_dir)
            raise
        finally:
            await asyncio.to_thread(_remove_file, config_path)


class _SubprocessBrowserServer:
    def __init__(
        self,
        process: aio_subprocess.Process,
        ws_endpoint: str,
        drain_tasks: list[asyncio.Task[None]],
        profile_dir: str,
    ) -> None:
        self._process = process
        self.ws_endpoint = ws_endpoint
        self._drain_tasks = drain_tasks
        self._profile_dir = profile_dir

    async def close(self) -> None:
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()

        for task in self._drain_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._profile_dir:
            await asyncio.to_thread(_remove_directory, self._profile_dir)
            self._profile_dir = ""


async def _drain_stream(stream: asyncio.StreamReader | None, prefix: str) -> None:
    """Continuously read a subprocess stream and log its output."""

    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        LOGGER.debug("%s: %s", prefix, line.decode().rstrip())


def _write_launch_config(options: dict[str, Any]) -> str:
    """Write launch configuration to a temporary JSON file."""

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as fh:
        json.dump(options, fh)
        fh.write("\n")
        return fh.name


def _remove_file(path: str) -> None:
    """Remove a file without raising if it does not exist."""

    with contextlib.suppress(FileNotFoundError):
        import os

        os.remove(path)


def _remove_directory(path: str) -> None:
    """Recursively delete ``path`` if it exists."""

    if not path:
        return
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(path)


async def _terminate_process(process: aio_subprocess.Process, *, kill: bool = False) -> None:
    """Terminate a subprocess and fall back to ``kill`` if needed."""

    if process.returncode is not None:
        return
    if not kill:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
            return
        except asyncio.TimeoutError:
            LOGGER.warning("Camoufox server did not exit after terminate; killing")
    process.kill()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)


__all__ = ["SessionManager", "SessionHandle", "VNCUnavailableError"]
