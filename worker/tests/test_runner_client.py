from __future__ import annotations

import asyncio

import httpx
from camofleet_worker.runner_client import RunnerClient


def test_runner_client_respects_base_url_path() -> None:
    """The runner client should honour path prefixes in the base URL."""

    async def exercise() -> None:
        captured: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json={})

        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(base_url="http://runner.test/api", transport=transport) as http_client:
            client = RunnerClient("http://runner.test/api", http_client=http_client)
            await client.get_session("abc")
            await client.close()
            assert not http_client.is_closed

        assert captured == ["http://runner.test/api/sessions/abc"]

    asyncio.run(exercise())
