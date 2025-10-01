"""Tests for the orchestrated runner HTTP helpers."""

from __future__ import annotations

import json
from typing import List, Tuple

import httpx
import pytest

from worker.jobs import Job, JobStatus
from worker.runner_orch import create_gateway_client, run_orchestrated_job


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """Limit anyio-powered tests to the asyncio backend."""

    return "asyncio"


async def test_run_orchestrated_job_successful_flow() -> None:
    """Execute the happy-path flow and capture session metadata in metrics."""

    call_log: List[Tuple[str, str]] = []
    poll_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_calls
        call_log.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer secret-token"

        if request.method == "POST" and request.url.path == "/sessions/commands":
            body = json.loads(request.content.decode())
            assert body["start_url"] == "https://example.com"
            assert body["idle_ttl_seconds"] == 60
            return httpx.Response(201, json={"id": "sess-1", "status": "INIT"}, request=request)

        if request.method == "POST" and request.url.path == "/sessions/sess-1/proxy":
            body = json.loads(request.content.decode())
            assert body == {"http": "http://user:pwd@proxy:8080"}
            return httpx.Response(200, json={"id": "sess-1", "status": "INIT"}, request=request)

        if request.method == "GET" and request.url.path == "/sessions/sess-1":
            poll_calls += 1
            if poll_calls == 1:
                return httpx.Response(
                    200,
                    json={"id": "sess-1", "status": "INIT", "last_seen_at": "2025-01-01T00:00:00Z"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={"id": "sess-1", "status": "READY", "last_seen_at": "2025-01-01T00:00:02Z"},
                request=request,
            )

        if request.method == "POST" and request.url.path == "/sessions/sess-1/touch":
            return httpx.Response(
                200,
                json={"id": "sess-1", "status": "READY", "last_seen_at": "2025-01-01T00:00:03Z"},
                request=request,
            )

        if request.method == "DELETE" and request.url.path == "/sessions/sess-1":
            return httpx.Response(204, request=request)

        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    transport = httpx.MockTransport(handler)
    job = Job(url="https://example.com", http_proxy="http://user:pwd@proxy:8080")

    async with create_gateway_client(
        "https://gateway.local", "secret-token", transport=transport
    ) as client:
        result = await run_orchestrated_job(
            job,
            client,
            poll_interval=0.0,
            poll_timeout=5.0,
            backoff=0.0,
        )

    assert result.ok is True
    assert result.status is JobStatus.SUCCESS
    assert result.metrics.extra["session_id"] == "sess-1"
    assert result.metrics.extra["poll_attempts"] == 2
    assert result.metrics.extra["session_status"] == "READY"
    assert result.metrics.extra["touched_at"] == "2025-01-01T00:00:03Z"
    assert sum(1 for method, path in call_log if path == "/sessions/commands") == 1
    assert sum(1 for method, path in call_log if path == "/sessions/sess-1") >= 2


async def test_poll_retries_and_metrics_are_recorded() -> None:
    """Retry transient gateway failures while preserving success semantics."""

    poll_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_requests

        if request.method == "POST" and request.url.path == "/sessions/commands":
            return httpx.Response(201, json={"id": "sess-2", "status": "INIT"}, request=request)

        if request.method == "GET" and request.url.path == "/sessions/sess-2":
            poll_requests += 1
            if poll_requests == 1:
                return httpx.Response(500, json={"detail": "temporary"}, request=request)
            return httpx.Response(200, json={"id": "sess-2", "status": "READY"}, request=request)

        if request.method == "POST" and request.url.path == "/sessions/sess-2/touch":
            return httpx.Response(200, json={"id": "sess-2", "status": "READY"}, request=request)

        if request.method == "DELETE" and request.url.path == "/sessions/sess-2":
            return httpx.Response(204, request=request)

        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    transport = httpx.MockTransport(handler)
    job = Job(url="https://retry.example")

    async with create_gateway_client(
        "https://gateway.local", "token", transport=transport
    ) as client:
        result = await run_orchestrated_job(
            job,
            client,
            poll_interval=0.0,
            poll_timeout=5.0,
            backoff=0.0,
        )

    assert poll_requests == 2
    assert result.ok is True
    assert result.status is JobStatus.SUCCESS
    assert result.metrics.extra["session_status"] == "READY"
    assert result.metrics.extra["poll_attempts"] == 1


async def test_run_orchestrated_job_failure_on_create() -> None:
    """Surface gateway creation failures as ``JobResult`` errors after retries."""

    create_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_calls
        if request.method == "POST" and request.url.path == "/sessions/commands":
            create_calls += 1
            return httpx.Response(500, json={"detail": "boom"}, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url.path}")

    transport = httpx.MockTransport(handler)
    job = Job(url="https://failure.example")

    async with create_gateway_client(
        "https://gateway.local", "token", transport=transport
    ) as client:
        result = await run_orchestrated_job(
            job,
            client,
            poll_interval=0.0,
            poll_timeout=1.0,
            backoff=0.0,
        )

    assert create_calls == 4  # initial attempt + 3 retries
    assert result.ok is False
    assert result.status is JobStatus.FAILURE
    assert result.error is not None
    assert result.error.type == "GatewayRequestError"
    assert "session_id" not in result.metrics.extra
