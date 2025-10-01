"""HTTP client used to communicate with runner control-plane endpoints."""

from __future__ import annotations

from typing import Any

import httpx
from core import Runner, Session

from ..models.session_launch import SessionLaunchPayload


class RunnerClientError(RuntimeError):
    """Raised when a runner call fails or returns an invalid payload."""


class RunnerControlClient:
    """Perform control-plane operations against runner instances."""

    def __init__(self, *, timeout: float = 10.0) -> None:
        """Initialise the client with the desired request timeout."""

        self._timeout = timeout

    async def create_session(
        self, runner: Runner, payload: SessionLaunchPayload
    ) -> Session:
        """Ask a runner to create a new session and return the resulting snapshot.

        Args:
            runner: Runner metadata that provides the base control-plane URL.
            payload: Validated launch settings received from the operator UI.

        Returns:
            Session: The runner-produced snapshot representing the new session.

        Raises:
            RunnerClientError: If the HTTP request fails or the response payload
                cannot be parsed into a :class:`core.Session` instance.
        """

        try:
            async with httpx.AsyncClient(
                base_url=str(runner.base_url), timeout=self._timeout
            ) as client:
                response = await client.post(
                    "/sessions",
                    json=payload.model_dump(exclude_none=True),
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - error branch
            raise RunnerClientError(
                f"Runner {runner.id} rejected session creation with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network failure
            raise RunnerClientError(
                f"Failed to contact runner {runner.id}: {exc!s}"
            ) from exc

        data: Any = response.json()
        try:
            return Session.model_validate(data)
        except Exception as exc:  # pragma: no cover - defensive
            raise RunnerClientError("Runner returned invalid session payload") from exc
