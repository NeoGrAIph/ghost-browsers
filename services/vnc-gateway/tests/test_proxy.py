"""Tests covering the RunnerProxy websocket implementation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from starlette import status
from websockets.exceptions import ConnectionClosedOK

from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.proxy import RunnerProxy
from tests.stubs import StubClientWebSocket


class StubRunnerConnection:
    """Deterministic upstream websocket used to simulate the Runner."""

    def __init__(self) -> None:
        self.subprotocol = "binary"
        self.sent: list[Any] = []
        self.closed = False
        self._incoming: asyncio.Queue[Any] = asyncio.Queue()

    async def send(self, payload: Any) -> None:
        """Record payloads forwarded by the gateway."""

        self.sent.append(payload)

    async def recv(self) -> Any:
        """Return the next payload destined for the client side."""

        payload = await self._incoming.get()
        if isinstance(payload, ConnectionClosedOK):
            raise payload
        return payload

    async def close(self) -> None:
        """Simulate closing the upstream websocket."""

        if self.closed:
            return
        self.closed = True
        await self._incoming.put(ConnectionClosedOK(1000, "runner closed"))

    def queue_incoming(self, payload: Any) -> None:
        """Queue a payload that should be delivered to the client."""

        self._incoming.put_nowait(payload)
class DummyConnectContext:
    """Context manager mimicking :func:`websockets.connect`."""

    def __init__(self, connection: StubRunnerConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> StubRunnerConnection:
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - standard signature
        await self._connection.close()


async def _run_forward_websocket_happy_path(monkeypatch) -> None:
    """Scenario helper for the happy path websocket relay test."""

    runner = StubRunnerConnection()

    def fake_connect(url: str, **kwargs: Any) -> DummyConnectContext:  # noqa: D401
        assert kwargs["subprotocols"] == ["binary"]
        assert kwargs["open_timeout"] > 0
        return DummyConnectContext(runner)

    monkeypatch.setattr("camou_vnc_gateway.proxy.websockets.connect", fake_connect)

    settings = Settings(token_secret="secret", runner_http_base="http://runner", runner_ws_base="ws://runner")
    proxy = RunnerProxy(settings)

    websocket = StubClientWebSocket(query_string="target_port=5901", headers={"sec-websocket-protocol": "binary"})

    runner.queue_incoming("runner-text")
    runner.queue_incoming(b"runner-bytes")
    websocket.queue_message({"type": "websocket.receive", "text": "client-text"})
    websocket.queue_message({"type": "websocket.receive", "bytes": b"client-bytes"})

    async def enqueue_disconnect() -> None:
        await asyncio.sleep(0)
        websocket.queue_message({"type": "websocket.disconnect"})

    asyncio.create_task(enqueue_disconnect())

    await proxy.forward_websocket(session_id="abc", websocket=websocket)

    assert websocket.accepted_subprotocol == "binary"
    assert websocket.sent_text == ["runner-text"]
    assert websocket.sent_bytes == [b"runner-bytes"]
    assert runner.sent == ["client-text", b"client-bytes"]


async def _run_forward_websocket_invalid_port(monkeypatch) -> None:
    """Scenario helper verifying policy violation on invalid target_port."""

    def fail_connect(*args: Any, **kwargs: Any) -> object:  # pragma: no cover - safety
        raise AssertionError("websockets.connect should not be invoked")

    monkeypatch.setattr("camou_vnc_gateway.proxy.websockets.connect", fail_connect)

    settings = Settings(token_secret="secret", runner_http_base="http://runner", runner_ws_base="ws://runner")
    proxy = RunnerProxy(settings)

    websocket = StubClientWebSocket(query_string="target_port=invalid")

    await proxy.forward_websocket(session_id="bad", websocket=websocket)

    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION
    assert websocket.close_reason is not None


async def _run_forward_websocket_network_error(monkeypatch) -> None:
    """Scenario helper verifying internal error on network failures."""

    def fake_connect(*args: Any, **kwargs: Any) -> DummyConnectContext:
        raise OSError("dial tcp: refused")

    monkeypatch.setattr("camou_vnc_gateway.proxy.websockets.connect", fake_connect)

    settings = Settings(token_secret="secret", runner_http_base="http://runner", runner_ws_base="ws://runner")
    proxy = RunnerProxy(settings)

    websocket = StubClientWebSocket()

    await proxy.forward_websocket(session_id="oops", websocket=websocket)

    assert websocket.close_code == status.WS_1011_INTERNAL_ERROR


def test_forward_websocket_happy_path(monkeypatch) -> None:
    """Proxy relays traffic in both directions and negotiates subprotocols."""

    asyncio.run(_run_forward_websocket_happy_path(monkeypatch))


def test_forward_websocket_invalid_port_closes_with_policy_violation(monkeypatch) -> None:
    """Invalid target_port results in a 1008 policy violation close code."""

    asyncio.run(_run_forward_websocket_invalid_port(monkeypatch))


def test_forward_websocket_network_error_closes_with_internal_error(monkeypatch) -> None:
    """Connection failures are surfaced to the client with close code 1011."""

    asyncio.run(_run_forward_websocket_network_error(monkeypatch))
