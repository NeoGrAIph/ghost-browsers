from __future__ import annotations

import asyncio

import httpx
from camofleet_control.config import ControlSettings, WorkerConfig
from camofleet_control.service import WorkerClient


def test_worker_client_respects_base_url_path() -> None:
    """Ensure worker client calls include any configured path prefix."""

    async def exercise() -> None:
        worker = WorkerConfig(name="prefixed", url="http://example.test/api")
        settings = ControlSettings(workers=[worker])
        captured: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, json=[])

        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(base_url=worker.url, transport=transport) as http_client:
            client = WorkerClient(worker, settings, http_client=http_client)
            await client.list_sessions()
            await client.close()
            assert not http_client.is_closed

        assert captured == ["http://example.test/api/sessions"]

    asyncio.run(exercise())
