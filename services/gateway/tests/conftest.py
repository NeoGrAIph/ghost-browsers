"""Shared testing fixtures for the gateway service."""
from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Iterator, Mapping

import httpx
import pytest


class HttpxMockTransport:
    """Queue-based mock transport for ``httpx.AsyncClient`` used in tests."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Initialise the transport and patch ``httpx.AsyncClient`` to use it."""

        self.requests: list[httpx.Request] = []
        self._responses: Deque[Callable[[httpx.Request], httpx.Response]] = deque()
        transport = httpx.MockTransport(self._handle_request)
        original_async_client = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            """Instantiate ``AsyncClient`` bound to the mock transport."""

            kwargs.setdefault("transport", transport)
            return original_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

    def _handle_request(self, request: httpx.Request) -> httpx.Response:
        """Return the next queued response for the incoming request."""

        self.requests.append(request)
        if not self._responses:
            raise AssertionError("No mock httpx responses enqueued")
        responder = self._responses.popleft()
        return responder(request)

    def enqueue_json(self, payload: Mapping[str, Any], *, status_code: int = 200) -> None:
        """Queue a JSON response for the next HTTPX request."""

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=status_code, json=payload, request=request)

        self._responses.append(responder)

    def enqueue_text(self, text: str, *, status_code: int = 200) -> None:
        """Queue a plain text response to trigger JSON decoding errors."""

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=status_code, text=text, request=request)

        self._responses.append(responder)

    def enqueue(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        """Queue a custom responder for advanced scenarios."""

        self._responses.append(responder)


@pytest.fixture
def httpx_mock_transport(monkeypatch: pytest.MonkeyPatch) -> Iterator[HttpxMockTransport]:
    """Provide a mock transport that intercepts ``httpx.AsyncClient`` requests."""

    transport = HttpxMockTransport(monkeypatch)
    yield transport
