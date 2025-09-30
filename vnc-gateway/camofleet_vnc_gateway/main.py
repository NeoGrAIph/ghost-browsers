"""FastAPI application that proxies VNC traffic through fixed ports."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import uuid
from functools import lru_cache
from collections.abc import Iterable, Mapping
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from .config import GatewaySettings, load_settings

LOGGER = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

TARGET_PORT_COOKIE = "vnc-target-port"


class GatewayState:
    """Mutable objects shared across request handlers."""

    def __init__(self, settings: GatewaySettings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.request_timeout)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def close(self) -> None:
        await self._client.aclose()


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    """Instantiate the FastAPI application that powers the gateway."""

    cfg = settings or load_settings()
    app = FastAPI(title="Camofleet VNC Gateway", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    state = GatewayState(cfg)

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover - FastAPI lifecycle
        await state.close()

    def get_state() -> GatewayState:
        return state

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def _proxy_http(
        request: Request,
        *,
        state: GatewayState,
        path_suffix: str,
    ) -> Response:
        raw_port, port_source = _select_target_port(
            query_value=request.query_params.get("target_port"),
            referer=request.headers.get("referer"),
            cookies=request.cookies,
        )
        try:
            port = state.settings.validate_port(raw_port)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        query_items = [
            (key, value) for key, value in request.query_params.multi_items() if key != "target_port"
        ]
        query_string = urlencode(query_items)

        upstream_url = _build_upstream_url(
            scheme=state.settings.runner_http_scheme,
            host=state.settings.runner_host,
            port=port,
            prefix=state.settings.normalised_prefix(),
            path_suffix=path_suffix,
            query=query_string,
        )

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        body = await request.body()
        try:
            response = await state.client.request(
                request.method,
                upstream_url,
                headers=headers,
                content=body if body else None,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        response = Response(
            content=response.content,
            status_code=response.status_code,
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            },
        )

        if port_source == "query":
            response.set_cookie(
                TARGET_PORT_COOKIE,
                str(port),
                path="/vnc",
                samesite="lax",
            )

        return response

    @app.api_route("/vnc", methods=["GET", "HEAD", "OPTIONS"])
    async def proxy_root(request: Request, state: GatewayState = Depends(get_state)) -> Response:
        return await _proxy_http(request, state=state, path_suffix="/")

    @app.api_route("/vnc/{path:path}", methods=["GET", "HEAD", "OPTIONS"])
    async def proxy_http(
        path: str,
        request: Request,
        state: GatewayState = Depends(get_state),
    ) -> Response:
        suffix = _normalise_client_path(f"/{path}" if path else "/")
        return await _proxy_http(request, state=state, path_suffix=suffix)

    @app.websocket("/vnc/websockify")
    async def proxy_websocket(websocket: WebSocket, state: GatewayState = Depends(get_state)) -> None:
        raw_port, _ = _select_target_port(
            query_value=websocket.query_params.get("target_port"),
            referer=websocket.headers.get("referer"),
            cookies=_parse_cookie_header(websocket.headers.get("cookie")),
        )
        try:
            port = state.settings.validate_port(raw_port)
        except ValueError as exc:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
            return

        query_items = [
            (key, value)
            for key, value in websocket.query_params.multi_items()
            if key != "target_port"
        ]
        query_string = urlencode(query_items)

        upstream_url = _build_upstream_url(
            scheme=state.settings.runner_ws_scheme,
            host=state.settings.runner_host,
            port=port,
            prefix=state.settings.normalised_prefix(),
            path_suffix="/websockify",
            query=query_string,
        )

        subprotocol_header = websocket.headers.get("sec-websocket-protocol")
        subprotocols = [
            item.strip()
            for item in (subprotocol_header.split(",") if subprotocol_header else [])
            if item.strip()
        ]

        extra_headers = _select_upstream_headers(websocket.headers.items())
        connect_kwargs = {
            "ping_interval": None,
            "subprotocols": subprotocols or None,
        }

        header_param = _websockets_extra_headers_param()
        if extra_headers and header_param:
            connect_kwargs[header_param] = extra_headers

        try:
            connect_ctx = websockets.connect(
                upstream_url,
                **connect_kwargs,
            )
            upstream = await connect_ctx.__aenter__()
            try:
                await websocket.accept(subprotocol=upstream.subprotocol)

                client_to_upstream = asyncio.create_task(
                    _forward_client_to_upstream(websocket, upstream),
                    name="vnc-gateway-client->upstream",
                )
                upstream_to_client = asyncio.create_task(
                    _forward_upstream_to_client(websocket, upstream),
                    name="vnc-gateway-upstream->client",
                )
                done, pending = await asyncio.wait(
                    {client_to_upstream, upstream_to_client},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    exc = task.exception()
                    if exc:
                        raise exc
            finally:
                await connect_ctx.__aexit__(None, None, None)
        except (ConnectionClosedError, ConnectionClosedOK):
            with contextlib.suppress(RuntimeError):
                await websocket.close()
        except Exception as exc:  # pragma: no cover - defensive logging path
            LOGGER.warning("WebSocket proxy failure: %s", exc)
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

    return app


def _build_upstream_url(
    *,
    scheme: str,
    host: str,
    port: int,
    prefix: str,
    path_suffix: str,
    query: str,
) -> str:
    path_suffix = path_suffix or "/"
    combined_path = _join_paths(prefix, path_suffix)
    if not combined_path.startswith("/"):
        combined_path = f"/{combined_path}"
    query_part = f"?{query}" if query else ""
    return f"{scheme}://{host}:{port}{combined_path}{query_part}"


def _normalise_client_path(path_suffix: str) -> str:
    """Strip session identifiers injected by public overrides.

    Operators often expose the gateway through ingress rules such as
    ``https://example/vnc/{id}``.  The control plane appends ``vnc.html`` from the
    runner payload, resulting in client requests like ``/vnc/<uuid>/vnc.html``.
    The upstream websockify server, however, serves assets from its document
    root, so the dynamic segment must be removed before proxying the request.
    """

    if not path_suffix or path_suffix == "/":
        return "/"

    has_leading_slash = path_suffix.startswith("/")
    segments = [segment for segment in path_suffix.split("/") if segment]
    if not segments:
        return "/" if has_leading_slash else ""

    first, *rest = segments
    try:
        uuid.UUID(first)
    except ValueError:
        stripped = segments
    else:
        stripped = rest

    if not stripped:
        return "/" if has_leading_slash else ""

    normalised = "/".join(stripped)
    return f"/{normalised}" if has_leading_slash else normalised


def _join_paths(prefix: str, suffix: str) -> str:
    prefix = (prefix or "").rstrip("/")
    suffix = suffix.lstrip("/")
    if prefix and suffix:
        return f"{prefix}/{suffix}"
    if prefix:
        return prefix
    if suffix:
        return f"/{suffix}"
    return "/"


def _select_upstream_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    allowed = {"origin", "user-agent", "cookie", "sec-websocket-extensions"}
    return [(key, value) for key, value in headers if key.lower() in allowed]


@lru_cache(maxsize=1)
def _websockets_extra_headers_param() -> str | None:
    """Return the keyword name accepted by :func:`websockets.connect`."""

    try:
        signature = inspect.signature(websockets.connect)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return "extra_headers"

    for candidate in ("extra_headers", "additional_headers"):
        if candidate in signature.parameters:
            return candidate

    LOGGER.debug(
        "websockets.connect does not accept extra headers; forwarding will be skipped"
    )
    return None


async def _forward_client_to_upstream(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                await upstream.close()
                break
            if "text" in message and message["text"] is not None:
                await upstream.send(message["text"])
            elif "bytes" in message and message["bytes"] is not None:
                await upstream.send(message["bytes"])
    except Exception:
        await upstream.close()
        raise


async def _forward_upstream_to_client(
    websocket: WebSocket, upstream: websockets.WebSocketClientProtocol
) -> None:
    try:
        async for data in upstream:
            if isinstance(data, (bytes, bytearray)):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()


def _select_target_port(
    *,
    query_value: str | None,
    referer: str | None,
    cookies: Mapping[str, str] | None,
) -> tuple[str | None, str | None]:
    """Choose the most appropriate source for ``target_port``."""

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
    """Return ``target_port`` value parsed from ``referer`` if available."""

    if not referer:
        return None

    parsed = urlparse(referer)
    query_params = parse_qs(parsed.query)
    values = query_params.get("target_port")
    if values:
        return values[0]
    return None


def _parse_cookie_header(header_value: str | None) -> dict[str, str]:
    """Parse a raw ``Cookie`` header into a dictionary."""

    if not header_value:
        return {}

    cookie = SimpleCookie()
    try:
        cookie.load(header_value)
    except Exception:  # pragma: no cover - defensive against malformed headers
        return {}

    return {key: morsel.value for key, morsel in cookie.items()}


__all__ = ["create_app"]
