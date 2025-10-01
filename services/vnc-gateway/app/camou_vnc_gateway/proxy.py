"""Utilities to proxy HTTP and WebSocket traffic to the Runner service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Iterable

import httpx
import websockets
from fastapi import Request, WebSocket
from fastapi.responses import Response, StreamingResponse

from .config import Settings

LOG = logging.getLogger(__name__)


class RunnerProxy:
    """Forward HTTP and WebSocket communication to the Runner backend.

    The implementation relies on :mod:`httpx` for HTTP traffic and the
    :mod:`websockets` package for bidirectional WebSocket streaming.  Only the
    minimal functionality required by the assignment is implemented; the class
    focuses on the two routes exposed by this service.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def forward_http(self, *, session_id: str, request: Request) -> Response:
        """Proxy an HTTP GET request to the Runner.

        Parameters
        ----------
        session_id:
            Identifier of the session for which metadata is being requested.
        request:
            Incoming FastAPI request object containing headers and query
            parameters.  Only ``GET`` is currently supported and bodies are not
            forwarded because the upstream endpoint merely exposes session
            metadata.
        """

        target_url = f"{self._settings.runner_http_base}/sessions/{session_id}"
        LOG.debug("Proxying HTTP request", extra={"session_id": session_id, "target": target_url})

        async with httpx.AsyncClient(follow_redirects=True) as client:
            upstream_response = await client.get(
                target_url,
                params=request.query_params,
                headers=self._filter_headers(request.headers.keys(), request.headers),
            )

        filtered_headers = self._filter_response_headers(upstream_response.headers)
        return StreamingResponse(
            content=upstream_response.aiter_bytes(),
            status_code=upstream_response.status_code,
            headers=dict(filtered_headers),
            media_type=upstream_response.headers.get("content-type"),
        )

    async def forward_websocket(self, *, session_id: str, websocket: WebSocket) -> None:
        """Proxy a WebSocket connection to the Runner service.

        The method waits for the client to connect, establishes an outbound
        connection to the Runner and then relays traffic between the two until
        either party disconnects.
        """

        target_url = f"{self._settings.runner_ws_base}/sessions/{session_id}/ws"
        LOG.debug(
            "Proxying websocket connection",
            extra={"session_id": session_id, "target": target_url},
        )

        await websocket.accept()

        async with websockets.connect(target_url) as runner_ws:
            async def client_to_runner() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        message_type = message.get("type")
                        if message_type == "websocket.disconnect":
                            await runner_ws.close()
                            break
                        data = message.get("text")
                        if data is not None:
                            await runner_ws.send(data)
                            continue
                        binary_data = message.get("bytes")
                        if binary_data is not None:
                            await runner_ws.send(binary_data)
                except Exception:  # pragma: no cover - defensive logging aid
                    LOG.exception("client_to_runner failed", extra={"session_id": session_id})
                    raise

            async def runner_to_client() -> None:
                try:
                    async for payload in runner_ws:
                        if isinstance(payload, str):
                            await websocket.send_text(payload)
                        else:
                            await websocket.send_bytes(payload)
                except Exception:  # pragma: no cover - defensive logging aid
                    LOG.exception("runner_to_client failed", extra={"session_id": session_id})
                    raise

            tasks = {
                asyncio.create_task(client_to_runner()),
                asyncio.create_task(runner_to_client()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                with suppress(asyncio.CancelledError):
                    await task

    @staticmethod
    def _filter_headers(keys: Iterable[str], headers: httpx.Headers) -> dict[str, str]:
        """Drop hop-by-hop headers that should not reach the Runner."""

        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        return {k: headers[k] for k in keys if k.lower() not in hop_by_hop and k.lower() != "host"}

    @staticmethod
    def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
        """Filter upstream response headers to remove hop-by-hop entries."""

        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}


__all__ = ["RunnerProxy"]
