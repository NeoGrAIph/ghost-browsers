"""Browser lifecycle helpers for launching and stopping Camoufox sessions."""

from __future__ import annotations

import asyncio
import json
import os
import re
from asyncio.subprocess import Process
from dataclasses import dataclass
from typing import Mapping, Sequence

from .config import RunnerSettings


class BrowserLaunchError(RuntimeError):
    """Raised when the runner fails to launch a managed browser process."""


@dataclass(slots=True)
class BrowserSessionHandle:
    """Represents a running Playwright-managed browser instance.

    Attributes:
        ws_endpoint: WebSocket endpoint exposed by Playwright for remote control.
        process: Underlying subprocess kept alive for the duration of the session.

    Example:
        >>> # handle = await launch_browser(  # doctest: +SKIP
        ...     settings,
        ...     browser="camoufox",
        ...     headless=True,
        ... )
        >>> # await handle.shutdown()  # doctest: +SKIP
    """

    ws_endpoint: str
    process: Process

    @property
    def pid(self) -> int | None:
        """Return the OS process identifier backing the Playwright server.

        Example:
            >>> handle.pid  # doctest: +SKIP
            4312
        """

        return self.process.pid

    async def shutdown(self, *, force: bool = False, timeout: float = 5.0) -> None:
        """Terminate the underlying Playwright process.

        Args:
            force: When ``True`` the process is killed immediately. Otherwise a
                graceful ``terminate`` signal is sent first.
            timeout: Seconds to wait for graceful termination before escalating
                to a forced kill. Ignored when ``force`` is ``True``.

        Example:
            >>> await handle.shutdown(force=False)  # doctest: +SKIP
        """

        if self.process.returncode is not None:
            return
        if force:
            self.process.kill()
            await self.process.wait()
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()


def _resolve_playwright_browser_name(name: str) -> str:
    """Map runner-level browser identifiers to Playwright CLI names.

    The runner exposes ``camoufox`` as the default browser identifier. The
    upstream Playwright driver, however, recognises only the built-in browser
    families (``chromium``, ``firefox``, ``webkit``).  Camoufox re-uses the
    Firefox driver under the hood while injecting its own binary via
    ``CAMOUFOX_BINARY``.  This helper keeps the public surface unchanged while
    translating the value so that the CLI accepts it.

    Args:
        name: Browser identifier received from session payloads or warm pool
            configuration.

    Returns:
        str: Name understood by the Playwright CLI.

    Example:
        >>> _resolve_playwright_browser_name("camoufox")
        'firefox'
    """

    mapping = {
        "camoufox": "firefox",
    }
    key = name.strip().lower()
    return mapping.get(key, name)


async def launch_browser(
    settings: RunnerSettings,
    *,
    browser: str,
    headless: bool,
    command: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    browser_flags: Mapping[str, str] | None = None,
    read_timeout: float = 10.0,
) -> BrowserSessionHandle:
    """Launch Playwright in ``launch-server`` mode and return its wsEndpoint.

    Args:
        settings: Runner configuration providing Camoufox binary details.
        browser: Browser engine identifier requested by the session payload.
        headless: Whether the browser should run in headless mode.
        command: Optional override for the CLI invocation. Defaults to
            ``[PLAYWRIGHT_CLI, "launch-server", "--browser", resolved_browser]``
            where ``PLAYWRIGHT_CLI`` comes from the environment (falling back to
            ``playwright``) and ``resolved_browser`` maps runner identifiers like
            ``camoufox`` to Playwright's native names.
        env: Additional environment variables merged with ``os.environ``.
        browser_flags: Mapping of Camoufox/Firefox specific flags that should
            be exported as environment variables before the Playwright process
            starts. Keys with ``None`` values are ignored.
        read_timeout: Seconds to wait for Playwright to emit the ``wsEndpoint``
            JSON payload before aborting the launch.

    Returns:
        BrowserSessionHandle: Handle encapsulating the running process.

    Raises:
        BrowserLaunchError: If Playwright fails to start or does not provide a
            valid ``wsEndpoint`` payload within ``read_timeout`` seconds.

    Example:
        >>> settings = RunnerSettings(  # doctest: +SKIP
        ...     runner_id="runner",
        ...     camoufox_path="/usr/bin/camoufox",
        ... )
        >>> # handle = await launch_browser(  # doctest: +SKIP
        ...     settings,
        ...     browser="camoufox",
        ...     headless=True,
        ... )
    """

    cli = os.environ.get("PLAYWRIGHT_CLI", "playwright")

    if command is None:
        resolved_browser = _resolve_playwright_browser_name(browser)
        command = [cli, "launch-server", "--browser", resolved_browser]
    launch_env = {**os.environ, "CAMOUFOX_BINARY": str(settings.camoufox_path)}
    if headless:
        launch_env.setdefault("CAMOUFOX_HEADLESS", "virtual")
    if env:
        launch_env.update(env)
    if browser_flags:
        launch_env.update({k: v for k, v in browser_flags.items() if v is not None})

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=launch_env,
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive branch
        raise BrowserLaunchError("Playwright CLI is not available") from exc

    if process.stdout is None:
        await _terminate_process(process, force=True)
        raise BrowserLaunchError("Playwright stdout pipe is not available")

    try:
        raw = await asyncio.wait_for(process.stdout.readline(), timeout=read_timeout)
    except asyncio.TimeoutError as exc:
        await _terminate_process(process, force=True)
        raise BrowserLaunchError("Timed out waiting for Playwright wsEndpoint") from exc

    if not raw:
        await _terminate_process(process, force=True)
        raise BrowserLaunchError("Playwright exited without providing wsEndpoint")

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        await _terminate_process(process, force=True)
        raise BrowserLaunchError("wsEndpoint payload contains invalid UTF-8") from exc

    ws_endpoint: str | None = None
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        text = decoded.strip()
        if text:
            match = re.search(r"wss?://[^\s\x1b]+", text)
            if match:
                ws_endpoint = match.group(0)
        if ws_endpoint is None:
            await _terminate_process(process, force=True)
            raise BrowserLaunchError(
                f"Invalid wsEndpoint payload from Playwright: {text!r}"
            ) from None
    else:
        ws_endpoint = payload.get("wsEndpoint") if isinstance(payload, dict) else None
        if not ws_endpoint:
            await _terminate_process(process, force=True)
            raise BrowserLaunchError("Playwright JSON payload missing wsEndpoint")

    if not isinstance(ws_endpoint, str) or not ws_endpoint.strip():
        await _terminate_process(process, force=True)
        raise BrowserLaunchError("wsEndpoint payload is empty")

    if process.returncode is not None:
        stderr_output = await process.stderr.read() if process.stderr else b""
        message = stderr_output.decode("utf-8", errors="ignore").strip()
        raise BrowserLaunchError(
            f"Playwright exited prematurely with code {process.returncode}: {message}"
        )

    ws_endpoint = ws_endpoint.strip()

    return BrowserSessionHandle(ws_endpoint=ws_endpoint, process=process)


async def _terminate_process(process: Process, *, force: bool = False) -> None:
    """Best-effort helper to terminate a Playwright subprocess.

    Args:
        process: Subprocess spawned for Playwright ``launch-server``.
        force: When ``True`` immediately kill the process, otherwise try
            ``terminate`` first.

    Example:
        >>> # await _terminate_process(process, force=False)  # doctest: +SKIP
    """

    if process.returncode is not None:
        return
    if force:
        process.kill()
        await process.wait()
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


__all__ = ["BrowserLaunchError", "BrowserSessionHandle", "launch_browser"]
