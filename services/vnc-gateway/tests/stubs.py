"""Reusable websocket test doubles used across integration/unit suites."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette import status
from starlette.datastructures import Headers, QueryParams
from starlette.websockets import WebSocketState


class StubClientWebSocket:
    """Minimal stand-in for :class:`starlette.websockets.WebSocket`."""

    def __init__(self, *, query_string: str = "", headers: dict[str, str] | None = None) -> None:
        self.headers = Headers(headers or {})
        self.query_params = QueryParams(query_string)
        self.application_state = WebSocketState.CONNECTING
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.accepted_subprotocol: str | None = None

    def queue_message(self, message: dict[str, Any]) -> None:
        """Inject a message that :meth:`receive` should return."""

        self._receive_queue.put_nowait(message)

    async def receive(self) -> dict[str, Any]:
        """Return the next queued websocket message."""

        message = await self._receive_queue.get()
        if message.get("type") == "websocket.disconnect":
            self.application_state = WebSocketState.DISCONNECTED
        return message

    async def send_text(self, data: str) -> None:
        """Record text frames delivered to the client."""

        if self.application_state is not WebSocketState.CONNECTED:
            raise RuntimeError("websocket not connected")
        self.sent_text.append(data)

    async def send_bytes(self, data: bytes) -> None:
        """Record binary frames delivered to the client."""

        if self.application_state is not WebSocketState.CONNECTED:
            raise RuntimeError("websocket not connected")
        self.sent_bytes.append(data)

    async def accept(self, subprotocol: str | None = None) -> None:
        """Mark the websocket as connected and capture the negotiated protocol."""

        self.application_state = WebSocketState.CONNECTED
        self.accepted_subprotocol = subprotocol

    async def close(
        self, *, code: int = status.WS_1000_NORMAL_CLOSURE, reason: str | None = None
    ) -> None:
        """Record close information for assertions."""

        self.application_state = WebSocketState.DISCONNECTED
        self.close_code = code
        self.close_reason = reason
