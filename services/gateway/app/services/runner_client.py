"""HTTP client wrapper for invoking Runner session commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

import httpx
from core import Runner, Session, SessionStatus
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, ValidationError


class RunnerCommandError(RuntimeError):
    """Raised when the Runner API rejects a session command."""


class SessionCreateCommand(BaseModel):
    """Simplified DTO accepted by the gateway when creating sessions.

    The payload captures the high-level intent from the UI. It is converted into
    the richer ``SessionCreatePayload`` understood by the runner service by
    :class:`RunnerCommandClient`.

    Example:
        >>> SessionCreateCommand(
        ...     browser_name="Chrome",
        ...     region="eu-central",
        ...     proxy_id="proxy-42",
        ... ).to_runner_payload()
        {
        ...     'browser': 'Chrome',
        ...     'headless': False,
        ...     'labels': {'region': 'eu-central', 'proxy_id': 'proxy-42'},
        ... }
    """

    model_config = ConfigDict(extra="forbid")

    runner_id: str | None = Field(
        default=None,
        description="Optional identifier of the target runner; if omitted the gateway selects one",
    )
    browser_name: str = Field(min_length=1, description="Human readable browser name")
    region: str = Field(min_length=1, description="Desired region label for the session")
    proxy_id: str | None = Field(
        default=None, description="Optional proxy identifier attached as a label"
    )
    headless: bool = Field(
        default=False,
        description="Flag indicating whether the session should run without VNC",
    )
    start_url: AnyUrl | None = Field(
        default=None,
        description="Optional URL that should be opened once the session starts",
    )

    def to_runner_payload(self) -> dict[str, Any]:
        """Render the command as a Runner ``SessionCreatePayload`` JSON body."""

        labels: dict[str, str] = {"region": self.region}
        if self.proxy_id is not None:
            labels["proxy_id"] = self.proxy_id
        payload: dict[str, Any] = {
            "browser": self.browser_name,
            "headless": self.headless,
            "labels": labels,
        }
        if self.start_url is not None:
            payload["start_url"] = str(self.start_url)
        return payload


class SessionUpdateCommand(BaseModel):
    """Subset of fields exposed for session updates via the gateway."""

    model_config = ConfigDict(extra="forbid")

    status: SessionStatus | None = Field(
        default=None, description="Optional status override propagated to the runner"
    )
    headless: bool | None = Field(
        default=None, description="Toggle headless mode on the runner"
    )
    labels: Mapping[str, str] | None = Field(
        default=None, description="Label updates merged on the runner side"
    )
    metadata: Mapping[str, Any] | None = Field(
        default=None, description="Metadata updates merged on the runner side"
    )
    reason: str | None = Field(
        default=None, description="Human readable explanation for the update"
    )

    def to_runner_payload(self) -> dict[str, Any]:
        """Render the command as a JSON body accepted by ``PATCH /sessions``."""

        payload = self.model_dump(exclude_none=True)
        if "labels" in payload and self.labels is not None:
            payload["labels"] = dict(self.labels)
        if "metadata" in payload and self.metadata is not None:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(slots=True)
class RunnerCommandClient:
    """Thin wrapper around :mod:`httpx` for issuing Runner API commands."""

    timeout: float = 10.0
    transport: httpx.BaseTransport | None = None

    async def create_session(
        self, runner: Runner, command: SessionCreateCommand
    ) -> Session:
        """Create a session on the given runner and return the stored object."""

        return await self._request(
            runner,
            "POST",
            "/sessions",
            json=command.to_runner_payload(),
            expected_status=201,
        )

    async def update_session(
        self,
        runner: Runner,
        session_id: UUID,
        command: SessionUpdateCommand,
    ) -> Session:
        """Patch a session on the runner and return the updated representation."""

        return await self._request(
            runner,
            "PATCH",
            f"/sessions/{session_id}",
            json=command.to_runner_payload(),
        )

    async def delete_session(self, runner: Runner, session_id: UUID) -> Session:
        """Terminate the session on the runner and return the final state."""

        return await self._request(runner, "DELETE", f"/sessions/{session_id}")

    async def list_sessions(self, runner: Runner) -> list[Session]:
        """Return the collection of active sessions stored on ``runner``.

        Args:
            runner: Runner descriptor identifying the HTTP base URL that should
                be queried.

        Returns:
            list[Session]: Validated session models returned by the runner. The
            order mirrors the payload received from the service.

        Raises:
            RunnerCommandError: If the runner responds with a non-array JSON
                payload or individual entries cannot be parsed as
                :class:`core.Session` objects.

        Example:
            >>> client = RunnerCommandClient()  # doctest: +SKIP
            >>> await client.list_sessions(runner)  # doctest: +SKIP
        """

        payload = await self._request_payload(runner, "GET", "/sessions")
        if not isinstance(payload, list):
            raise RunnerCommandError(
                f"Runner {runner.id} responded with non-array payload for GET /sessions"
            )

        sessions: list[Session] = []
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise RunnerCommandError(
                    f"Runner {runner.id} returned a non-object entry at index {index}"
                )
            try:
                sessions.append(Session.model_validate(item))
            except ValidationError as exc:  # pragma: no cover - validation guard
                raise RunnerCommandError(
                    f"Runner {runner.id} returned an invalid session at index {index}"
                ) from exc
        return sessions

    async def _request(
        self,
        runner: Runner,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        expected_status: int = 200,
    ) -> Session:
        """Execute a Runner API call and parse the ``Session`` response.

        Args:
            runner: Runner descriptor identifying the API endpoint.
            method: HTTP verb issued against the runner.
            path: Path relative to the runner base URL.
            json: Optional JSON body sent with the request.
            expected_status: HTTP status code considered successful.

        Returns:
            Session: Validated session snapshot returned by the runner.

        Raises:
            RunnerCommandError: If the request fails, the status code differs
                from ``expected_status`` or the payload cannot be validated.

        Example:
            >>> client = RunnerCommandClient()  # doctest: +SKIP
            >>> await client._request(runner, "DELETE", "/sessions/1")  # doctest: +SKIP
        """

        payload = await self._request_payload(
            runner,
            method,
            path,
            json=json,
            expected_status=expected_status,
        )
        if not isinstance(payload, Mapping):
            raise RunnerCommandError(
                f"Runner {runner.id} returned an unexpected payload for {method} {path}"
            )
        try:
            return Session.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - validation guard
            raise RunnerCommandError(
                f"Runner {runner.id} returned an invalid session payload"
            ) from exc

    async def _request_payload(
        self,
        runner: Runner,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        expected_status: int = 200,
    ) -> Any:
        """Execute a Runner API call and return the parsed JSON body.

        Args:
            runner: Runner descriptor identifying the API endpoint.
            method: HTTP verb issued against the runner.
            path: Relative path requested on the runner.
            json: Optional JSON payload included in the request.
            expected_status: HTTP status code considered successful.

        Returns:
            Any: Parsed JSON payload from the runner response.

        Raises:
            RunnerCommandError: If the HTTP request fails, returns an
                unexpected status code or the body is not valid JSON.

        Example:
            >>> client = RunnerCommandClient()  # doctest: +SKIP
            >>> await client._request_payload(runner, "GET", "/sessions")  # doctest: +SKIP
        """

        try:
            async with httpx.AsyncClient(
                base_url=str(runner.base_url),
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(method, path, json=json)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - mapped error
            raise RunnerCommandError(
                f"Runner {runner.id} rejected {method} {path} with {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:  # pragma: no cover - network failure guard
            raise RunnerCommandError(
                f"Failed to execute {method} {path} against runner {runner.id}"
            ) from exc

        if response.status_code != expected_status:
            raise RunnerCommandError(
                f"Runner {runner.id} responded with unexpected status {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise RunnerCommandError(
                f"Runner {runner.id} returned non-JSON payload for {method} {path}"
            ) from exc


__all__ = [
    "RunnerCommandClient",
    "RunnerCommandError",
    "SessionCreateCommand",
    "SessionUpdateCommand",
]
