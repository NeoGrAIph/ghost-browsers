"""HTTP client facade to worker APIs."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from .config import ControlSettings, WorkerConfig


class WorkerClient:
    """A reusable async HTTP client that targets a worker."""

    def __init__(
        self,
        worker: WorkerConfig,
        settings: ControlSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # Store the configuration so helper methods can access metadata such as
        # VNC overrides if needed in the future.
        self.worker = worker
        self._settings = settings
        # ``base_url`` means we only have to supply paths (``/sessions`` etc.).
        if http_client is None:
            self._client = httpx.AsyncClient(
                base_url=worker.url,
                timeout=settings.request_timeout,
            )
            self._owns_client = True
        else:
            self._client = http_client
            self._owns_client = False

    async def health(self) -> httpx.Response:
        """Perform a GET request against the worker's /health endpoint."""

        return await self._client.get("health")

    async def list_sessions(self) -> httpx.Response:
        """Return all sessions currently reported by the worker."""

        return await self._client.get("sessions")

    async def get_session(self, session_id: str) -> httpx.Response:
        """Retrieve a single session by identifier."""

        return await self._client.get(f"sessions/{session_id}")

    async def delete_session(self, session_id: str) -> httpx.Response:
        """Forward a delete request to the worker."""

        return await self._client.delete(f"sessions/{session_id}")

    async def create_session(self, payload: dict) -> httpx.Response:
        """Create a session by POSTing to the worker."""

        return await self._client.post("sessions", json=payload)

    async def touch_session(self, session_id: str) -> httpx.Response:
        """Refresh the worker's idle timeout for the given session."""

        return await self._client.post(f"sessions/{session_id}/touch")

    async def close(self) -> None:
        """Release HTTP connections held by the underlying client."""

        if self._owns_client:
            await self._client.aclose()


@asynccontextmanager
async def worker_client(worker: WorkerConfig, settings: ControlSettings):
    """Context manager that yields a :class:`WorkerClient` instance."""

    client = WorkerClient(worker, settings)
    try:
        yield client
    finally:
        await client.close()


__all__ = ["WorkerClient", "worker_client"]
