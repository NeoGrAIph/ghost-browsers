"""Tests for browser launch helpers used by the runner service."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

import pytest
from app.browser import _resolve_playwright_browser_name, launch_browser
from app.config import RunnerSettings


@pytest.fixture()
def anyio_backend() -> str:
    """Run AnyIO-powered tests on the asyncio backend."""

    return "asyncio"


class _DummyStream:
    """Async stream stub that returns a predefined payload once."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._consumed = False

    async def readline(self) -> bytes:
        """Return the payload on first invocation and EOF afterwards."""

        if self._consumed:
            return b""
        self._consumed = True
        return self._payload

    async def read(self) -> bytes:
        """Expose payload for stderr compatibility helpers."""

        return self._payload


class _DummyProcess:
    """Subprocess stub emulating Playwright's launch-server lifecycle."""

    def __init__(self, payload: bytes) -> None:
        self.stdout = _DummyStream(payload)
        self.stderr = _DummyStream(b"")
        self.returncode: int | None = None
        self.pid = 4321

    def terminate(self) -> None:
        """Emulate graceful termination signal."""

        self.returncode = 0

    def kill(self) -> None:
        """Emulate forced process termination."""

        self.returncode = -9

    async def wait(self) -> None:
        """No-op wait compatible with asyncio subprocess protocol."""

        self.returncode = 0


def _make_launch_stub(
    recorded: dict[str, Any],
    payload: bytes,
) -> Callable[..., Awaitable[_DummyProcess]]:
    async def _fake_subprocess_exec(*args: Any, **kwargs: Any) -> _DummyProcess:
        recorded["args"] = args
        recorded["env"] = kwargs.get("env", {})
        return _DummyProcess(payload)

    return _fake_subprocess_exec


@pytest.mark.anyio("asyncio")
@pytest.mark.parametrize(
    "payload, expected",
    [
        (json.dumps({"wsEndpoint": "ws://dummy-json"}).encode("utf-8") + b"\n", "ws://dummy-json"),
        (b"Websocket endpoint:\x1b[93m ws://dummy-ansi \x1b[0m\n", "ws://dummy-ansi"),
        (b"ws://dummy-plain\n", "ws://dummy-plain"),
    ],
)
async def test_launch_browser_parses_ws_payload(
    payload: bytes,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the launcher accepts JSON, ANSI-decorated, and plain ws payloads."""

    recorded: dict[str, Any] = {}
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _make_launch_stub(recorded, payload))
    settings = RunnerSettings(runner_id="runner-test", camoufox_path="/usr/bin/camoufox")

    handle = await launch_browser(settings, browser="camoufox", headless=True)

    args = recorded["args"]
    assert args[:3] == ("playwright", "launch-server", "--browser")
    assert args[3] == "firefox"
    assert recorded["env"]["CAMOUFOX_BINARY"] == str(settings.camoufox_path)
    assert handle.ws_endpoint == expected


def test_resolve_playwright_browser_name() -> None:
    """Verify translation between runner identifiers and Playwright names."""

    assert _resolve_playwright_browser_name("camoufox") == "firefox"
    assert _resolve_playwright_browser_name("chromium") == "chromium"
