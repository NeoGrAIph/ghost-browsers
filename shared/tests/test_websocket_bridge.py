from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import WebSocketDisconnect

from shared.websocket_bridge import bridge_websocket


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeWebSocket:
    def __init__(self, messages: list[dict | BaseException]):
        self._messages = list(messages)
        self.sent: list[tuple[str, str | bytes]] = []
        self.close_calls: list[tuple[int, str]] = []

    async def receive(self) -> dict:
        if not self._messages:
            raise RuntimeError("No more messages")
        message = self._messages.pop(0)
        if isinstance(message, BaseException):
            raise message
        return message

    async def send_text(self, data: str) -> None:
        self.sent.append(("text", data))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.close_calls.append((code, reason or ""))


class FakeUpstream:
    def __init__(self, outgoing: list[str | bytes]):
        self._outgoing = list(outgoing)
        self.sent: list[str | bytes] = []
        self.closed = False
        self.pings: list[bytes] = []
        self.pongs: list[bytes] = []

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)

    def ping(self, data: bytes) -> asyncio.Future[None]:
        self.pings.append(data)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        future.set_result(None)
        return future

    async def pong(self, data: bytes) -> None:
        self.pongs.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str | bytes:
        if self._outgoing:
            return self._outgoing.pop(0)
        raise StopAsyncIteration


@asynccontextmanager
async def fake_connect(upstream: FakeUpstream):
    yield upstream


@pytest.mark.anyio("asyncio")
async def test_bridge_websocket_proxies_messages() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "websocket.receive", "text": "hello"},
            {"type": "websocket.receive", "bytes": b"binary"},
            {"type": "websocket.disconnect", "code": 1000},
        ]
    )
    upstream = FakeUpstream(["world", b"bytes-reply"])

    await bridge_websocket(websocket, lambda: fake_connect(upstream))

    assert upstream.sent == ["hello", b"binary"]
    assert websocket.sent == [("text", "world"), ("bytes", b"bytes-reply")]
    assert websocket.close_calls  # closed once upstream finished


@pytest.mark.anyio("asyncio")
async def test_bridge_websocket_handles_disconnect() -> None:
    websocket = FakeWebSocket([WebSocketDisconnect(code=1001)])
    upstream = FakeUpstream([])

    await bridge_websocket(websocket, lambda: fake_connect(upstream))

    assert upstream.closed is True
    assert websocket.close_calls  # closed by upstream forwarder


@pytest.mark.anyio("asyncio")
async def test_bridge_websocket_forwards_ping_pong() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "websocket.receive", "ping": b"ping"},
            {"type": "websocket.receive", "pong": b"pong"},
            {"type": "websocket.disconnect", "code": 1000},
        ]
    )
    upstream = FakeUpstream([])

    await bridge_websocket(websocket, lambda: fake_connect(upstream))

    assert upstream.pings == [b"ping"]
    assert upstream.pongs == [b"pong"]
