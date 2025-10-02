"""Integration tests exercising the websocket proxy against a live endpoint."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import websockets
from starlette import status

from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.proxy import RunnerProxy
from tests.stubs import StubClientWebSocket as _StubClientWebSocket


async def _run_forward_websocket_round_trip(port: int) -> None:
    """Websocket relay exchanges frames with an upstream server."""

    received_by_runner: list[Any] = []

    async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
        async for payload in websocket:
            received_by_runner.append(payload)
            if isinstance(payload, str):
                await websocket.send(f"runner::{payload}")
            else:
                await websocket.send(b"runner::" + payload)

    server = await websockets.serve(handler, "127.0.0.1", port)
    try:
        settings = Settings(
            token_secret="secret",
            runner_http_base="http://runner",
            runner_ws_base=f"ws://127.0.0.1:{port}",
        )
        proxy = RunnerProxy(settings)
        websocket = _StubClientWebSocket(headers={"sec-websocket-protocol": "binary"})
        websocket.queue_message({"type": "websocket.receive", "text": "hello"})

        async def enqueue_disconnect() -> None:
            await asyncio.sleep(0.05)
            websocket.queue_message({"type": "websocket.disconnect"})

        asyncio.create_task(enqueue_disconnect())

        await proxy.forward_websocket(session_id="session", websocket=websocket)

        assert received_by_runner == ["hello"]
        assert websocket.sent_text == ["runner::hello"]
        assert websocket.sent_bytes == []
    finally:
        server.close()
        await server.wait_closed()
        await proxy.aclose()


async def _run_forward_websocket_connection_failure(port: int) -> None:
    """Connection errors result in an internal-error close on the client."""

    settings = Settings(
        token_secret="secret",
        runner_http_base="http://runner",
        runner_ws_base=f"ws://127.0.0.1:{port}",
    )
    proxy = RunnerProxy(settings)
    websocket = _StubClientWebSocket()

    await proxy.forward_websocket(session_id="session", websocket=websocket)

    assert websocket.close_code == status.WS_1011_INTERNAL_ERROR
    await proxy.aclose()


def _allocate_unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_forward_websocket_round_trip() -> None:
    """Websocket relay exchanges frames with an upstream server."""

    port = _allocate_unused_tcp_port()
    asyncio.run(_run_forward_websocket_round_trip(port))


def test_forward_websocket_connection_failure() -> None:
    """Connection errors result in an internal-error close on the client."""

    port = _allocate_unused_tcp_port()
    asyncio.run(_run_forward_websocket_connection_failure(port))
