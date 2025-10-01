"""Integration tests that exercise the session lifecycle end-to-end."""

from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from httpx import AsyncClient

from app.config import RunnerSettings
from app.dependencies.session_manager import (
    get_event_publisher,
    get_runner_settings,
    get_session_manager,
)
from app.events import InMemorySessionEventPublisher
from app.main import app
from app.session_manager import SessionCreatePayload, SessionManager


@pytest.mark.anyio("asyncio")
async def test_session_creation_returns_live_ws_endpoint() -> None:
    """POST /sessions should return a usable wsEndpoint backed by the stub server."""

    stub_path = Path(__file__).with_name("playwright_stub_server.py")
    settings = RunnerSettings(
        runner_id="runner-integration",
        camoufox_path=stub_path,
        vnc_enabled=False,
    )
    publisher = InMemorySessionEventPublisher()
    manager = SessionManager(settings, publisher)

    app.dependency_overrides[get_runner_settings] = lambda: settings
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    app.dependency_overrides[get_session_manager] = lambda: manager
    app.state.session_manager_override = manager

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/sessions", json=SessionCreatePayload().model_dump(exclude_none=True)
            )
            assert response.status_code == 201
            payload = response.json()
            endpoint = payload["ws_endpoint"]
            await _expect_websocket_handshake(endpoint)

            session_id = payload["id"]
            delete = await client.delete(f"/sessions/{session_id}")
            assert delete.status_code == 200

            # Allow the shutdown command to propagate before re-connecting.
            await asyncio.sleep(0.1)
            with pytest.raises(OSError):
                await _raw_open(endpoint)
    finally:
        app.dependency_overrides.clear()
        if hasattr(app.state, "session_manager_override"):
            delattr(app.state, "session_manager_override")
        await manager.shutdown()


async def _expect_websocket_handshake(endpoint: str) -> None:
    """Perform a raw WebSocket handshake against ``endpoint`` and assert success."""

    reader, writer = await _raw_open(endpoint)
    try:
        parsed = urlparse(endpoint)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        host = parsed.hostname or "127.0.0.1"
        headers = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(headers.encode())
        await writer.drain()
        response = await reader.readuntil(b"\r\n\r\n")
    finally:
        writer.close()
        await writer.wait_closed()
    assert b"101 Switching Protocols" in response


async def _raw_open(endpoint: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a raw TCP connection for the supplied WebSocket endpoint."""

    parsed = urlparse(endpoint)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        raise ValueError("Endpoint must include an explicit port")
    return await asyncio.open_connection(host, port)
