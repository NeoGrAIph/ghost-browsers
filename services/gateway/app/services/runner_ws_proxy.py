"""Utilities for relaying session WebSocket connections to runners."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Iterable

import websockets
from fastapi import WebSocket
from starlette import status
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

LOGGER = logging.getLogger(__name__)


class RunnerWebSocketProxyError(RuntimeError):
    """Raised when the gateway fails to establish or maintain a WS tunnel."""


@dataclass(slots=True)
class RunnerWebSocketProxy:
    """Bidirectionally proxy WebSocket frames between the UI and a runner.

    Instances of this class are lightweight and share no connection state. They
    exist primarily so the application can expose configuration knobs (timeouts
    and header forwarding rules) from a single location. The class mirrors the
    production gateway's approach by initiating the upstream connection before
    accepting the client socket to ensure subprotocol negotiation is preserved.
    """

    connect_timeout: float = 5.0

    async def proxy(self, *, client: WebSocket, target: str) -> None:
        """Relay traffic between ``client`` and the runner ``target`` endpoint.

        Args:
            client: Accepted FastAPI WebSocket representing the UI connection.
            target: Absolute WebSocket URL exposed by the runner for the
                session's Playwright instance.

        Raises:
            RunnerWebSocketProxyError: If the upstream connection cannot be
                established or a fatal relay error occurs. The client socket is
                closed with an appropriate policy or internal error code before
                the exception bubbles up to the caller.

        Example:
            >>> proxy = RunnerWebSocketProxy()
            >>> await proxy.proxy(  # doctest: +SKIP
            ...     client=websocket,
            ...     target="ws://runner-1/playwright/123",
            ... )
        """

        subprotocols = _extract_subprotocols(client.headers.get("sec-websocket-protocol"))
        headers = _filter_upstream_headers(client.headers.items())
        connect_kwargs: dict[str, object] = {"ping_interval": None}
        if subprotocols:
            connect_kwargs["subprotocols"] = subprotocols
        if headers:
            connect_kwargs["extra_headers"] = headers

        try:
            if self.connect_timeout and self.connect_timeout > 0:
                async with asyncio.timeout(self.connect_timeout):
                    upstream = await websockets.connect(target, **connect_kwargs)
            else:
                upstream = await websockets.connect(target, **connect_kwargs)
        except TimeoutError as exc:  # pragma: no cover - defensive guard
            await client.close(
                code=status.WS_1011_INTERNAL_ERROR,
                reason="Upstream connection timed out",
            )
            raise RunnerWebSocketProxyError("Timed out connecting to runner") from exc
        except Exception as exc:  # pragma: no cover - connection refused, DNS
            await client.close(
                code=status.WS_1011_INTERNAL_ERROR,
                reason="Failed to connect to runner",
            )
            raise RunnerWebSocketProxyError("Failed to connect to runner") from exc

        try:
            await client.accept(subprotocol=upstream.subprotocol)
        except Exception as exc:  # pragma: no cover - FastAPI handshake failure
            await upstream.close(code=status.WS_1011_INTERNAL_ERROR)
            raise RunnerWebSocketProxyError("Failed to accept WebSocket client") from exc

        try:
            await self._relay(client, upstream)
        finally:
            await upstream.close()

    async def _relay(self, client: WebSocket, upstream: websockets.WebSocketClientProtocol) -> None:
        """Relay frames between ``client`` and ``upstream`` until disconnect.

        Example:
            >>> await proxy._relay(client, upstream)  # doctest: +SKIP
        """

        async def client_to_runner() -> None:
            try:
                while True:
                    message = await client.receive()
                    message_type = message.get("type")
                    if message_type == "websocket.disconnect":
                        await upstream.close(code=message.get("code"))
                        break
                    text_payload = message.get("text")
                    if text_payload is not None:
                        await upstream.send(text_payload)
                        continue
                    binary_payload = message.get("bytes")
                    if binary_payload is not None:
                        await upstream.send(binary_payload)
            except Exception:  # pragma: no cover - logged for diagnostics
                LOGGER.exception("client_to_runner relay failed")
                raise

        async def runner_to_client() -> None:
            try:
                async for payload in upstream:
                    if isinstance(payload, str):
                        await client.send_text(payload)
                    else:
                        await client.send_bytes(payload)
            except ConnectionClosedOK:
                await client.close(code=status.WS_1000_NORMAL_CLOSURE)
            except ConnectionClosedError as exc:
                await client.close(
                    code=exc.code or status.WS_1011_INTERNAL_ERROR,
                    reason=exc.reason,
                )
                raise
            except Exception:  # pragma: no cover - logged for diagnostics
                LOGGER.exception("runner_to_client relay failed")
                raise

        tasks = {
            asyncio.create_task(client_to_runner()),
            asyncio.create_task(runner_to_client()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            with contextlib.suppress(asyncio.CancelledError):
                exc = task.exception()
                if exc:
                    raise RunnerWebSocketProxyError("WebSocket relay failed") from exc


def _extract_subprotocols(header_value: str | None) -> list[str]:
    """Return a list of subprotocol tokens extracted from the header value.

    Example:
        >>> _extract_subprotocols("playwright, trace")
        ['playwright', 'trace']
    """

    if not header_value:
        return []
    return [token.strip() for token in header_value.split(",") if token.strip()]


def _filter_upstream_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Filter hop-by-hop headers that should not be forwarded upstream.

    Example:
        >>> _filter_upstream_headers([
        ...     ("connection", "keep-alive"),
        ...     ("sec-websocket-protocol", "playwright"),
        ... ])
        [('sec-websocket-protocol', 'playwright')]
    """

    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "sec-websocket-accept",
        "sec-websocket-extensions",
        "sec-websocket-key",
        "sec-websocket-protocol",
        "sec-websocket-version",
    }
    return [(key, value) for key, value in headers if key.lower() not in hop_by_hop]


__all__ = ["RunnerWebSocketProxy", "RunnerWebSocketProxyError"]
