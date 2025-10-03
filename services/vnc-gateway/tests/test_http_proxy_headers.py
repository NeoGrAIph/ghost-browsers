"""HTTP proxy tests covering response header handling semantics."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.proxy import RunnerProxy
from fastapi import Request


def _build_request() -> Request:
    """Create a minimal ASGI ``Request`` suitable for ``forward_http`` tests."""

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sessions/test",
        "headers": [(b"accept", b"application/json")],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


async def _run_forward_http_preserves_duplicate_set_cookie(monkeypatch) -> None:
    """Execute the duplicate ``Set-Cookie`` preservation scenario."""

    settings = Settings(
        token_secret="secret",
        runner_http_base="http://runner",  # actual host mocked below
        runner_ws_base="ws://runner",
    )
    proxy = RunnerProxy(settings)

    upstream_headers = httpx.Headers(
        [
            ("Set-Cookie", "a=1; Path=/"),
            ("Set-Cookie", "b=2; Path=/"),
            ("Content-Type", "application/json"),
        ]
    )
    upstream_response = httpx.Response(200, headers=upstream_headers, content=b"{}")

    async def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        return upstream_response

    monkeypatch.setattr(proxy._client, "request", fake_request)  # type: ignore[attr-defined]

    request = _build_request()
    response = await proxy.forward_http(session_id="test", request=request)

    try:
        assert response.status_code == upstream_response.status_code
        assert response.headers.getlist("set-cookie") == [
            "a=1; Path=/",
            "b=2; Path=/",
        ]
        assert response.headers["content-type"] == "application/json"
    finally:
        await proxy.aclose()


def test_forward_http_preserves_duplicate_set_cookie(monkeypatch) -> None:
    """The HTTP proxy forwards duplicate ``Set-Cookie`` headers without loss."""

    asyncio.run(_run_forward_http_preserves_duplicate_set_cookie(monkeypatch))
