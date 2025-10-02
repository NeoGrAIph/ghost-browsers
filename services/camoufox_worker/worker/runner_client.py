"""Async HTTP client wrapper for interacting with the Camoufox runner."""

from __future__ import annotations

from typing import Any

import httpx


class RunnerClient:
    """Thin convenience wrapper around the runner REST API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout) if http_client is None else http_client

    async def close(self) -> None:
        """Close the underlying HTTP client if it was created by the wrapper."""

        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        """Retrieve the runner health payload."""

        response = await self._client.get("health")
        response.raise_for_status()
        return response.json()

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return the list of active sessions maintained by the runner."""

        response = await self._client.get("sessions")
        response.raise_for_status()
        return response.json()

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ask the runner to create a new browser session."""

        response = await self._client.post("sessions", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Return metadata for a specific session identifier."""

        response = await self._client.get(f"sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        """Request graceful termination of a session."""

        response = await self._client.delete(f"sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def touch_session(self, session_id: str) -> dict[str, Any]:
        """Refresh the idle timeout for ``session_id``."""

        response = await self._client.post(f"sessions/{session_id}/touch")
        response.raise_for_status()
        return response.json()


__all__ = ["RunnerClient"]

