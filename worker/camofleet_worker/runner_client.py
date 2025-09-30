"""HTTP client wrapper for the Camoufox runner sidecar."""

from __future__ import annotations

import httpx


class RunnerClient:
    """Async wrapper around the runner REST API.

    The worker service does not want to know the precise HTTP semantics of the
    runner sidecar; it only needs a high level API.  This class keeps all HTTP
    concerns in a single place and exposes small helper methods that match the
    operations performed by the worker handlers.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # ``AsyncClient`` maintains connection pools and handles retries/timeouts
        # for us.  ``base_url`` ensures all requests are routed to the runner.
        if http_client is None:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                timeout=timeout,
            )
            self._owns_client = True
        else:
            self._client = http_client
            self._owns_client = False

    async def close(self) -> None:
        """Close the underlying HTTP client and release sockets."""

        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> dict:
        """Return the runner health payload."""

        response = await self._client.get("health")
        response.raise_for_status()
        return response.json()

    async def list_sessions(self) -> list[dict]:
        """Fetch a list of sessions managed by the runner."""

        response = await self._client.get("sessions")
        response.raise_for_status()
        return response.json()

    async def create_session(self, payload: dict) -> dict:
        """Instruct the runner to create a new browser session."""

        response = await self._client.post("sessions", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_session(self, session_id: str) -> dict:
        """Retrieve information about a specific session."""

        response = await self._client.get(f"sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def delete_session(self, session_id: str) -> dict:
        """Ask the runner to terminate a session."""

        response = await self._client.delete(f"sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def touch_session(self, session_id: str) -> dict:
        """Refresh a session's idle timeout."""

        response = await self._client.post(f"sessions/{session_id}/touch")
        response.raise_for_status()
        return response.json()

