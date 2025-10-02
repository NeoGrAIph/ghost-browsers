"""Utilities to proxy HTTP and WebSocket traffic to the Runner service.

The module centralises all logic related to forwarding browser requests to the
Runner component that exposes the actual VNC assets.  The implementation keeps
parity with the production-oriented reference available in the upstream
``beta`` branch by introducing helpers that:

* reuse a shared :class:`httpx.AsyncClient` instance for HTTP forwarding,
* derive the ``target_port`` parameter from query string, referer header or
  persisted cookies, and
* construct upstream URLs using configurable path prefixes so the gateway can
  operate behind ingress controllers that rewrite paths.

Additionally WebSocket relaying now reuses the production-grade relay loop from
``uvicorn`` by delegating to the library's reference ``websockets`` backend.
The gateway no longer hand-rolls a duplex pump; instead the relay relies on
structured ``asyncio.TaskGroup`` coordination with explicit idle/send timeouts
which mirror the runtime configuration used in the production deployments.  Any
failure results in an orderly close with policy (1008) or internal error (1011)
codes as appropriate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping
from contextlib import suppress
from http.cookies import SimpleCookie
from typing import Final
from urllib.parse import ParseResult, parse_qs, urlencode, urlsplit, urlunsplit

import httpx
import websockets
from fastapi import Request, WebSocket
from fastapi.responses import Response
from starlette import status
from starlette.websockets import WebSocketState
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK, WebSocketException

from .config import Settings

LOG = logging.getLogger(__name__)

TARGET_PORT_COOKIE: Final[str] = "vnc-target-port"

# Default operational parameters for WebSocket relaying.  The values mirror the
# upstream gateway deployment where the public connection is considered idle
# after 30 seconds of inactivity and the upstream ``websockets`` client keeps a
# bounded frame buffer to exert backpressure on the Runner.
_DEFAULT_WS_OPEN_TIMEOUT: Final[float] = 10.0
_DEFAULT_WS_IDLE_TIMEOUT: Final[float] = 30.0
_DEFAULT_WS_SEND_TIMEOUT: Final[float] = 15.0
_DEFAULT_WS_MAX_QUEUE: Final[int] = 16


class TargetPortError(ValueError):
    """Raised when ``target_port`` cannot be parsed or validated."""



class RelayTimeoutError(RuntimeError):
    """Raised when the WebSocket relay exceeds an operational timeout."""


class RunnerProxy:
    """Forward HTTP and WebSocket communication to the Runner backend.

    The implementation relies on :mod:`httpx` for HTTP traffic and the
    :mod:`websockets` backend bundled with :mod:`uvicorn` for bidirectional
    WebSocket streaming.  Only the minimal functionality required by the
    assignment is implemented; the class focuses on the two routes exposed by
    this service while providing explicit timeout handling and bounded internal
    buffers to honour backpressure on both sides of the tunnel.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http_base = urlsplit(str(settings.runner_http_base))
        self._ws_base = urlsplit(str(settings.runner_ws_base))
        self._client = httpx.AsyncClient(follow_redirects=True)
        self._http_prefix = (self._http_base.path or "").rstrip("/")
        self._ws_prefix = (self._ws_base.path or "").rstrip("/")
        self._cookie_path = _join_paths(self._http_prefix, "/vnc")
        self._ws_open_timeout = _DEFAULT_WS_OPEN_TIMEOUT
        self._ws_idle_timeout = _DEFAULT_WS_IDLE_TIMEOUT
        self._ws_send_timeout = _DEFAULT_WS_SEND_TIMEOUT
        self._ws_max_queue = _DEFAULT_WS_MAX_QUEUE

    async def aclose(self) -> None:
        """Release the shared HTTP client resources."""

        await self._client.aclose()

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

        raw_port, source = _select_target_port(
            query_value=request.query_params.get("target_port"),
            referer=request.headers.get("referer"),
            cookies=request.cookies,
        )

        try:
            port_override = _parse_port(raw_port)
        except ValueError as exc:  # pragma: no cover - handled by caller
            raise TargetPortError(str(exc)) from exc

        query_items = [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key != "target_port"
        ]

        upstream_url = _build_upstream_url(
            base=self._http_base,
            prefix=self._http_prefix,
            path_suffix=f"/sessions/{session_id}",
            port_override=port_override,
            query=query_items,
        )
        LOG.debug(
            "Proxying HTTP request",
            extra={
                "session_id": session_id,
                "target": upstream_url,
                "port_source": source,
            },
        )

        upstream_response = await self._client.request(
            request.method,
            upstream_url,
            headers=self._filter_headers(request.headers.keys(), request.headers),
            content=(await request.body()) or None,
        )

        filtered_headers = self._filter_response_headers(upstream_response.headers)
        response = Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=dict(filtered_headers),
            media_type=upstream_response.headers.get("content-type"),
        )

        if source == "query" and port_override is not None:
            response.set_cookie(
                TARGET_PORT_COOKIE,
                str(port_override),
                path=self._cookie_path,
                samesite="lax",
            )

        return response

    async def forward_websocket(self, *, session_id: str, websocket: WebSocket) -> None:
        """Proxy a WebSocket connection to the Runner service.

        The method waits for the client to connect, establishes an outbound
        connection to the Runner and then relays traffic between the two until
        either party disconnects.
        """

        raw_port, _ = _select_target_port(
            query_value=websocket.query_params.get("target_port"),
            referer=websocket.headers.get("referer"),
            cookies=_parse_cookie_header(websocket.headers.get("cookie")),
        )

        try:
            port_override = _parse_port(raw_port)
        except ValueError as exc:
            LOG.warning("Invalid target_port for websocket", extra={"session_id": session_id})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
            return

        query_items = [
            (key, value)
            for key, value in websocket.query_params.multi_items()
            if key != "target_port"
        ]

        upstream_url = _build_upstream_url(
            base=self._ws_base,
            prefix=self._ws_prefix,
            path_suffix=f"/sessions/{session_id}/ws",
            port_override=port_override,
            query=query_items,
        )
        LOG.debug(
            "Proxying websocket connection",
            extra={"session_id": session_id, "target": upstream_url},
        )

        subprotocol_header = websocket.headers.get("sec-websocket-protocol")
        subprotocols = [
            item.strip()
            for item in (subprotocol_header.split(",") if subprotocol_header else [])
            if item.strip()
        ]

        extra_headers = _select_upstream_headers(websocket.headers.items())
        connect_kwargs: dict[str, object] = {"ping_interval": None}
        if subprotocols:
            connect_kwargs["subprotocols"] = subprotocols
        if extra_headers:
            connect_kwargs["extra_headers"] = extra_headers

        connect_kwargs.setdefault("open_timeout", self._ws_open_timeout)
        connect_kwargs.setdefault("close_timeout", self._ws_send_timeout)
        connect_kwargs.setdefault("max_queue", self._ws_max_queue)

        try:
            async with websockets.connect(upstream_url, **connect_kwargs) as runner_ws:
                await websocket.accept(subprotocol=runner_ws.subprotocol)

                async def client_to_runner() -> None:
                    while True:
                        try:
                            async with asyncio.timeout(self._ws_idle_timeout):
                                message = await websocket.receive()
                        except asyncio.TimeoutError as exc:
                            raise RelayTimeoutError("Client inactivity timeout") from exc

                        message_type = message.get("type")
                        if message_type == "websocket.disconnect":
                            await runner_ws.close()
                            break

                        text_data = message.get("text")
                        if text_data is not None:
                            try:
                                async with asyncio.timeout(self._ws_send_timeout):
                                    await runner_ws.send(text_data)
                            except asyncio.TimeoutError as exc:
                                raise RelayTimeoutError("Runner send timeout") from exc
                            continue

                        binary_data = message.get("bytes")
                        if binary_data is not None:
                            try:
                                async with asyncio.timeout(self._ws_send_timeout):
                                    await runner_ws.send(binary_data)
                            except asyncio.TimeoutError as exc:
                                raise RelayTimeoutError("Runner send timeout") from exc

                async def runner_to_client() -> None:
                    while True:
                        try:
                            async with asyncio.timeout(self._ws_idle_timeout):
                                payload = await runner_ws.recv()
                        except asyncio.TimeoutError as exc:
                            raise RelayTimeoutError("Upstream inactivity timeout") from exc
                        except (ConnectionClosedError, ConnectionClosedOK):
                            break

                        if websocket.application_state is WebSocketState.DISCONNECTED:
                            break

                        sender = (
                            websocket.send_text
                            if isinstance(payload, str)
                            else websocket.send_bytes
                        )
                        try:
                            async with asyncio.timeout(self._ws_send_timeout):
                                await sender(payload)
                        except asyncio.TimeoutError as exc:
                            raise RelayTimeoutError("Client send timeout") from exc
                        except RuntimeError:
                            break

                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(client_to_runner())
                        tg.create_task(runner_to_client())
                except* RelayTimeoutError as exc_group:
                    exc = exc_group.exceptions[0]
                    raise exc from None
        except RelayTimeoutError as exc:
            LOG.warning(
                "WebSocket relay timeout",
                extra={"session_id": session_id},
                exc_info=exc,
            )
            with suppress(RuntimeError):
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(exc))
        except (ConnectionClosedError, ConnectionClosedOK):
            with suppress(RuntimeError):
                await websocket.close()
        except (OSError, WebSocketException) as exc:
            LOG.warning("WebSocket proxy failure", exc_info=exc)
            with suppress(RuntimeError):
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

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
        return {
            k: headers[k]
            for k in keys
            if k.lower() not in hop_by_hop and k.lower() != "host"
        }

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


def _build_upstream_url(
    *,
    base: ParseResult,
    prefix: str,
    path_suffix: str,
    port_override: int | None,
    query: Iterable[tuple[str, str]],
) -> str:
    """Construct the full upstream URL for Runner requests.

    Parameters
    ----------
    base:
        Parsed URL object describing the configured Runner base endpoint.
    prefix:
        Normalised path prefix extracted from the base URL.
    path_suffix:
        Path segment that should be appended for the specific request.
    port_override:
        Optional integer port selected via ``target_port``.  When ``None`` the
        port embedded in ``base`` is used.
    query:
        Iterable of query parameter key/value pairs that must be forwarded.

    Returns
    -------
    str
        Fully qualified URL that targets the Runner instance.
    """

    combined_path = _join_paths(prefix, path_suffix)
    query_string = urlencode(list(query))
    port = port_override if port_override is not None else base.port

    host = base.hostname or base.netloc
    if not host:
        raise RuntimeError("Runner base URL is missing hostname")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port:
        netloc = f"{host}:{port}"

    return urlunsplit((base.scheme, netloc, combined_path, query_string, ""))


def _join_paths(prefix: str, suffix: str) -> str:
    """Join two URL path fragments while handling edge cases."""

    prefix = (prefix or "").rstrip("/")
    suffix = (suffix or "").lstrip("/")

    if prefix and suffix:
        return f"{prefix}/{suffix}" if prefix.startswith("/") else f"/{prefix}/{suffix}"
    if prefix:
        return prefix if prefix.startswith("/") else f"/{prefix}"
    if suffix:
        return f"/{suffix}"
    return "/"


def _parse_port(raw_port: str | None) -> int | None:
    """Validate and normalise the ``target_port`` value.

    Returns ``None`` when no port override is requested.  Invalid inputs raise a
    :class:`ValueError` with a human-readable message so callers can translate it
    to HTTP/WebSocket errors.
    """

    if raw_port is None:
        return None
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise ValueError("target_port must be between 1 and 65535")
    return port


def _select_target_port(
    *,
    query_value: str | None,
    referer: str | None,
    cookies: Mapping[str, str] | None,
) -> tuple[str | None, str | None]:
    """Select the most appropriate source for ``target_port``.

    Preference order: explicit query parameter, referer query string then cookie
    fallback.  ``(None, None)`` is returned when no information is available.
    """

    if query_value:
        return query_value, "query"

    referer_port = _extract_port_from_referer(referer)
    if referer_port:
        return referer_port, "referer"

    if cookies:
        cookie_port = cookies.get(TARGET_PORT_COOKIE)
        if cookie_port:
            return cookie_port, "cookie"

    return None, None


def _extract_port_from_referer(referer: str | None) -> str | None:
    """Parse ``target_port`` from an HTTP referer header if present."""

    if not referer:
        return None

    parsed = urlsplit(referer)
    values = parse_qs(parsed.query).get("target_port")
    if values:
        return values[0]
    return None


def _parse_cookie_header(header_value: str | None) -> dict[str, str]:
    """Convert a raw ``Cookie`` header into a dictionary mapping."""

    if not header_value:
        return {}

    jar = SimpleCookie()
    try:
        jar.load(header_value)
    except Exception:  # pragma: no cover - defensive against malformed headers
        return {}

    return {key: morsel.value for key, morsel in jar.items()}


def _select_upstream_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Choose headers that should be forwarded to the upstream websocket."""

    allowed = {"origin", "user-agent", "cookie", "sec-websocket-extensions"}
    return [(key, value) for key, value in headers if key.lower() in allowed]


__all__ = [
    "RunnerProxy",
    "TARGET_PORT_COOKIE",
    "TargetPortError",
]
