"""Tests covering configurable metrics backends."""

from __future__ import annotations

import asyncio

import camou_vnc_gateway.metrics as gateway_metrics
from camou_vnc_gateway.config import Settings
from camou_vnc_gateway.dependencies import (
    get_connection_registry,
    get_runner_proxy,
    get_token_validator,
)
from camou_vnc_gateway.main import create_app
from camou_vnc_gateway.token import TokenValidator
from fastapi import Request
from fastapi.testclient import TestClient
from security.vnc import VncTokenService

from tests.dummy_metrics_backend import CUSTOM_REGISTRY, DUMMY_EXPORTER


class _StubRunnerProxy:
    """Runner proxy that records forwarded HTTP requests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Request]] = []

    async def forward_http(self, *, session_id: str, request: Request) -> dict[str, str]:
        """Record the forwarded request and return a deterministic payload."""

        self.calls.append((session_id, request))
        return {"session": session_id}

    async def forward_websocket(
        self, *, session_id: str, websocket
    ) -> None:  # pragma: no cover - unused
        """Unused stub to satisfy the proxy interface."""

        raise AssertionError("websocket forwarding is not used in this test")


def test_connection_registry_uses_custom_prometheus_registry() -> None:
    """Registry is created using the configured CollectorRegistry factory."""

    settings = Settings(
        token_secret="custom-registry",
        runner_http_base="http://runner",
        runner_ws_base="ws://runner",
        metrics_backend="prometheus",
        metrics_registry_import="tests.dummy_metrics_backend:get_registry",
    )
    registry = get_connection_registry(settings)

    async def _simulate() -> None:
        async with registry.track(session_id="abc", channel="http"):
            pass

    asyncio.run(_simulate())

    assert gateway_metrics.METRICS_REGISTRY is CUSTOM_REGISTRY
    value = CUSTOM_REGISTRY.get_sample_value(
        "camou_vnc_gateway_connection_opens_total", {"channel": "http"}
    )
    assert value == 1.0


def test_metrics_route_returns_404_when_prometheus_disabled() -> None:
    """OTLP backend disables the Prometheus endpoint while emitting events."""

    settings = Settings(
        token_secret="otlp-secret",
        runner_http_base="http://runner",
        runner_ws_base="ws://runner",
        metrics_backend="otlp",
        metrics_otlp_exporter_import="tests.dummy_metrics_backend:get_exporter",
    )
    app = create_app(settings=settings)
    proxy = _StubRunnerProxy()
    validator = TokenValidator(secret=settings.token_secret)
    token_service = VncTokenService(secret=settings.token_secret, ttl_seconds=60)

    app.dependency_overrides[get_runner_proxy] = lambda: proxy
    app.dependency_overrides[get_token_validator] = lambda: validator

    client = TestClient(app)
    token, _ = token_service.issue("session-otlp")
    response = client.get("/sessions/session-otlp", headers={"X-VNC-Token": token})

    assert response.status_code == 200
    assert proxy.calls[0][0] == "session-otlp"

    connection_events = [event for event in DUMMY_EXPORTER.events if "connection" in event.name]
    assert connection_events, "expected OTLP exporter to receive connection metrics"

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 404
