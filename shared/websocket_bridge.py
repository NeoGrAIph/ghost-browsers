"""Utilities for proxying WebSocket traffic between services."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from fastapi import WebSocket, WebSocketDisconnect, status
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class SupportsPing(Protocol):
    def ping(self, data: bytes | None = None) -> Awaitable[object]:
        """Send a ping frame upstream."""


@runtime_checkable
class SupportsPong(Protocol):
    async def pong(self, data: bytes | None = None) -> None:
        """Send a pong frame upstream."""


UpstreamProtocol = websockets.WebSocketClientProtocol
ConnectCallable = Callable[[], AbstractAsyncContextManager[UpstreamProtocol]]


async def bridge_websocket(
    websocket: WebSocket,
    connect_upstream: ConnectCallable,
    *,
    logger: logging.Logger | None = None,
    log_context: str = "websocket bridge",
    error_close_code: int = status.WS_1011_INTERNAL_ERROR,
) -> None:
    """Stream messages bidirectionally between a FastAPI WebSocket and upstream server.

    Args:
        websocket: The WebSocket connected to the client.
        connect_upstream: A callable returning an async context manager yielding the
            upstream :class:`~websockets.WebSocketClientProtocol` connection.
        logger: Optional logger used for reporting unexpected failures.
        log_context: Human readable description included in log messages.
        error_close_code: Close code to report to the client when unexpected
            errors occur while proxying messages.
    """

    logger = logger or LOGGER
    try:
        async with connect_upstream() as upstream:
            forward_client = asyncio.create_task(
                _forward_client_to_upstream(websocket, upstream),
                name=f"{log_context}-client->upstream",
            )
            forward_upstream = asyncio.create_task(
                _forward_upstream_to_client(websocket, upstream),
                name=f"{log_context}-upstream->client",
            )
            done, pending = await asyncio.wait(
                {forward_client, forward_upstream},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                try:
                    task.result()
                except asyncio.CancelledError:  # pragma: no cover - propagate cancellation
                    raise
    except asyncio.CancelledError:  # pragma: no cover - shutdown handling
        raise
    except (ConnectionClosedError, ConnectionClosedOK, WebSocketDisconnect):
        with contextlib.suppress(RuntimeError):
            await websocket.close()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("%s failure: %s", log_context, exc)
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=error_close_code)


async def _forward_client_to_upstream(
    websocket: WebSocket,
    upstream: UpstreamProtocol,
) -> None:
    """Forward client messages to the upstream worker WebSocket."""

    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                await upstream.close()
                break
            if message_type != "websocket.receive":
                continue
            data = message.get("text")
            if data is not None:
                await upstream.send(data)
                continue
            data_bytes = message.get("bytes")
            if data_bytes is not None:
                await upstream.send(data_bytes)
                continue
            if "ping" in message:
                _send_ping(upstream, message.get("ping"))
                continue
            if "pong" in message:
                await _send_pong(upstream, message.get("pong"))
    except WebSocketDisconnect:
        await upstream.close()


async def _forward_upstream_to_client(
    websocket: WebSocket,
    upstream: UpstreamProtocol,
) -> None:
    """Forward upstream worker messages to the client WebSocket."""

    try:
        async for data in upstream:
            if isinstance(data, (bytes, bytearray)):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()


def _send_ping(upstream: UpstreamProtocol, data: bytes | None) -> None:
    if isinstance(upstream, SupportsPing):
        upstream.ping(data or b"")


async def _send_pong(upstream: UpstreamProtocol, data: bytes | None) -> None:
    if isinstance(upstream, SupportsPong):
        await upstream.pong(data or b"")


__all__ = ["bridge_websocket"]
