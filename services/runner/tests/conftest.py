"""Shared pytest fixtures for the runner service test suite."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from app.session_manager import SessionCreatePayload, SessionManager


@pytest.fixture
def anyio_backend() -> str:
    """Force the anyio plugin to use the asyncio backend."""

    return "asyncio"


@pytest.fixture
def fake_playwright(monkeypatch: pytest.MonkeyPatch) -> dict[UUID, "FakeProcess"]:
    """Stub Playwright lifecycle hooks to avoid spawning real browsers."""

    processes: dict[UUID, FakeProcess] = {}

    class FakeProcess:
        """Lightweight substitute for :class:`asyncio.subprocess.Process`."""

        def __init__(self) -> None:
            self.returncode: int | None = None
            self.terminate_called = False
            self.kill_called = False

        def terminate(self) -> None:
            self.terminate_called = True
            self.returncode = 0

        def kill(self) -> None:
            self.kill_called = True
            self.returncode = -9

        async def wait(self) -> int:
            await asyncio.sleep(0)
            return 0 if self.returncode is None else self.returncode

    async def fake_start(self, session_id: UUID, payload: SessionCreatePayload):
        process = FakeProcess()
        processes[session_id] = process
        return process, f"ws://127.0.0.1/fake/{session_id}"

    monkeypatch.setattr(SessionManager, "_start_browser_process", fake_start)
    return processes
