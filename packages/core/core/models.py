"""Shared domain models for Camou Core.

The models defined here capture the cross-service contract for Runner
lifecycle, Session state, and Session event propagation. They are
consumed by the Runner, Gateway, VNC Gateway, and UI components to
exchange strongly-typed payloads via REST, SSE, and WebSocket channels.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, FrozenSet
from uuid import UUID, uuid4

from pydantic import (
    AliasChoices,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class RunnerState(str, Enum):
    """Operational state reported by a Runner instance.

    The state is used by the Gateway to prioritise runners when
    allocating new sessions and by the UI to visualise runner health.

    Attributes:
        STARTING: Runner is booting Playwright/Firefox.
        IDLE: Runner is ready to accept new sessions.
        BUSY: Runner is running the maximum number of sessions.
        DEGRADED: Runner is reachable but health checks failed.
        OFFLINE: Runner is not reachable (last heartbeat timed out).

    Example:
        >>> RunnerState.IDLE.value
        'idle'
    """

    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class SessionStatus(str, Enum):
    """Lifecycle phases emitted by runners for browser sessions.

    The values mirror the production Camoufox runner implementation used in the
    beta branch. ``INIT`` represents a newly created session, ``READY`` a
    session that accepted commands, ``TERMINATING`` an in-flight shutdown, and
    ``DEAD`` a fully released session. Services consuming events should treat
    ``DEAD`` as the only terminal state.

    Example:
        >>> SessionStatus.INIT.value
        'INIT'
    """

    INIT = "INIT"
    READY = "READY"
    TERMINATING = "TERMINATING"
    DEAD = "DEAD"


class StartUrlWait(str, Enum):
    """Describe how the runner waits for an optional start URL to load.

    ``NONE`` skips automatic navigation, ``DOM_CONTENT_LOADED`` waits for the
    DOMContentLoaded event, and ``LOAD`` waits for a full page load. These values
    align with the beta implementation and surface directly to UI clients and
    automation tooling.

    Example:
        >>> StartUrlWait.LOAD.value
        'load'
    """

    NONE = "none"
    DOM_CONTENT_LOADED = "domcontentloaded"
    LOAD = "load"


class SessionEventType(str, Enum):
    """Event types emitted by runners towards the gateway/UI.

    Example:
        >>> SessionEventType.CREATED.value
        'session.created'
    """

    CREATED = "session.created"
    UPDATED = "session.updated"
    ENDED = "session.ended"


class SessionProxySettings(BaseModel):
    """Proxy configuration attached to a session.

    Attributes:
        http: Optional HTTP proxy URL.
        https: Optional HTTPS proxy URL.
        socks: Optional SOCKS proxy URL.

    Example:
        >>> SessionProxySettings(http="http://proxy.local:3128").model_dump()
        {'http': 'http://proxy.local:3128', 'https': None, 'socks': None}
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    http: AnyUrl | None = Field(default=None, description="HTTP proxy to use for the session")
    https: AnyUrl | None = Field(default=None, description="HTTPS proxy to use for the session")
    socks: AnyUrl | None = Field(default=None, description="SOCKS proxy to use for the session")

    @model_validator(mode="after")
    def ensure_at_least_one_proxy(self) -> "SessionProxySettings":
        """Validate that at least one proxy endpoint is configured.

        Returns:
            SessionProxySettings: The validated proxy configuration instance.

        Raises:
            ValueError: If none of ``http``, ``https`` or ``socks`` is provided.

        Example:
            >>> SessionProxySettings(http="http://proxy.local:3128")
            SessionProxySettings(http=Url('http://proxy.local:3128/'), https=None, socks=None)
        """

        if not any((self.http, self.https, self.socks)):
            raise ValueError(
                "at least one proxy URL must be provided when proxy settings are declared"
            )
        return self


class SessionVncDetails(BaseModel):
    """VNC connection parameters exposed to UI clients.

    The beta implementation exposes both HTTP and WebSocket URLs and, in the
    newer contract, the gateway may additionally attach a short-lived token that
    the VNC proxy validates.  At least one of ``http_url`` or ``websocket_url``
    must be present; tokens must never exceed the global 300 second TTL.

    Example:
        >>> SessionVncDetails(
        ...     http_url="https://vnc.example/view/abc",
        ...     websocket_url="wss://vnc.example/ws/abc",
        ...     token="opaque",
        ...     token_ttl_seconds=120,
        ... ).token_ttl_seconds
        120
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    http_url: AnyUrl | None = Field(
        default=None,
        description="Public HTTP URL that renders the VNC viewer",
    )
    websocket_url: AnyUrl | None = Field(
        default=None,
        description="WebSocket endpoint proxied by the VNC gateway",
    )
    token: str | None = Field(
        default=None,
        description="Short-lived VNC access token issued by the gateway",
    )
    token_ttl_seconds: PositiveInt | None = Field(
        default=None,
        description="Number of seconds before the VNC token expires (<= 300)",
    )

    @field_validator("token")
    @classmethod
    def _trim_token(cls, value: str | None) -> str | None:
        """Strip incidental whitespace from tokens before validation.

        Args:
            value: Raw token value supplied by the gateway.

        Returns:
            str | None: The trimmed token or ``None`` when not provided.

        Raises:
            ValueError: If the token becomes empty after trimming.

        Example:
            >>> SessionVncDetails._trim_token("  opaque  ")
            'opaque'
        """

        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("token must contain non-whitespace characters")
        return trimmed

    @model_validator(mode="after")
    def check_payload(self) -> "SessionVncDetails":
        """Validate cross-field invariants for VNC connection data.

        Returns:
            SessionVncDetails: The validated VNC descriptor.

        Raises:
            ValueError: If no URL is provided, the token TTL exceeds 300 seconds,
                or a token is supplied without a TTL.

        Example:
            >>> SessionVncDetails(
            ...     websocket_url="wss://vnc/ws", token="opaque", token_ttl_seconds=60
            ... ).token_ttl_seconds
            60
        """

        if not any((self.http_url, self.websocket_url)):
            raise ValueError("at least one of http_url or websocket_url must be provided")
        if self.token_ttl_seconds is not None and self.token_ttl_seconds > 300:
            raise ValueError("token_ttl_seconds must be <= 300")
        if self.token is not None and self.token_ttl_seconds is None:
            raise ValueError("token_ttl_seconds must be provided when token is set")
        return self


class Runner(BaseModel):
    """Metadata reported by a runner instance.

    Attributes:
        id: Stable runner identifier (unique within the cluster).
        base_url: Base HTTP URL for runner control API.
        state: Operational state of the runner.
        total_slots: Maximum concurrent sessions supported.
        available_slots: Currently free slots; derived from total minus active sessions.
        healthy: Whether the runner passes health checks.
        supports_vnc: Whether the runner can expose VNC previews.
        last_heartbeat_at: Timestamp of the most recent heartbeat.
        capabilities: Arbitrary capability flags advertised by the runner.

    Example:
        >>> Runner(id="runner-1", base_url="http://runner:8080", total_slots=4).available_slots
        4
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Runner identifier")
    base_url: AnyUrl = Field(description="Base URL for runner control plane")
    state: RunnerState = Field(default=RunnerState.STARTING, description="Operational state")
    total_slots: PositiveInt = Field(description="Total concurrent sessions supported")
    available_slots: int | None = Field(
        default=None,
        ge=0,
        description="Number of free session slots (<= total_slots)",
    )
    healthy: bool = Field(default=True, description="True if health checks pass")
    supports_vnc: bool = Field(default=False, description="Runner can allocate VNC sessions")
    last_heartbeat_at: datetime | None = Field(
        default=None,
        description="Timestamp of the last heartbeat received by the gateway",
    )
    capabilities: FrozenSet[str] = Field(
        default_factory=frozenset,
        description="Optional capability flags published by the runner",
    )

    @field_validator("id")
    @classmethod
    def _strip_identifier(cls, value: str) -> str:
        """Normalise runner identifiers prior to validation.

        Args:
            value: Identifier provided by the runner.

        Returns:
            str: The stripped identifier string.

        Raises:
            ValueError: If the identifier is blank after trimming.

        Example:
            >>> Runner._strip_identifier("  runner-1  ")
            'runner-1'
        """

        trimmed = value.strip()
        if not trimmed:
            raise ValueError("id must not be empty or whitespace only")
        return trimmed

    @model_validator(mode="after")
    def _post_init(self) -> "Runner":
        """Derive defaults and enforce field relationships.

        Returns:
            Runner: The validated runner instance with ``available_slots`` populated.

        Raises:
            ValueError: If ``available_slots`` is negative, exceeds ``total_slots``,
                the runner is ``OFFLINE`` yet marked ``healthy``, or the heartbeat
                timestamp lacks timezone information.

        Example:
            >>> Runner(
            ...     id="runner-1", base_url="http://runner:8080", total_slots=2,
            ...     available_slots=1, state=RunnerState.IDLE
            ... )
            Runner(id='runner-1', base_url=AnyUrl('http://runner:8080', ...), ...)
        """

        object.__setattr__(
            self,
            "available_slots",
            self.total_slots if self.available_slots is None else self.available_slots,
        )
        if self.available_slots < 0:
            raise ValueError("available_slots must be >= 0")
        if self.available_slots > self.total_slots:
            raise ValueError("available_slots cannot exceed total_slots")
        if self.state == RunnerState.OFFLINE and self.healthy:
            raise ValueError("offline runners cannot be marked healthy")
        if self.last_heartbeat_at is not None and self.last_heartbeat_at.tzinfo is None:
            raise ValueError("last_heartbeat_at must be timezone-aware")
        return self


class Session(BaseModel):
    """Aggregate representing a browser session lifecycle.

    Attributes:
        id: Session UUID generated by the runner.
        runner_id: Identifier of the runner hosting the session.
        status: Lifecycle status reported by the runner.
        created_at: Timestamp when the session object was created.
        last_seen_at: Timestamp of the last runner-issued heartbeat/update.
        ended_at: Optional timestamp when the session finished.
        start_url: Optional URL loaded when the session starts.
        start_url_wait: How long the runner waits for the start URL to load.
        headless: Whether the browser runs without a VNC preview.
        idle_ttl_seconds: Idle timeout for the session in seconds (30–3600).
        browser: Browser engine backing the session (e.g. ``camoufox``).
        labels: User-provided labels propagated across services.
        ws_endpoint: Public WebSocket endpoint for controlling the session.
        proxy: Optional proxy settings that apply to the session.
        vnc: Optional VNC connection details for the UI.
        vnc_enabled: Whether a VNC preview is currently available.
        metadata: Free-form metadata shared with the UI.

    Example:
        >>> session = Session(
        ...     id=uuid4(),
        ...     runner_id="runner-1",
        ...     status=SessionStatus.INIT,
        ...     created_at=datetime.now(datetime.UTC),
        ...     last_seen_at=datetime.now(datetime.UTC),
        ...     headless=False,
        ...     idle_ttl_seconds=300,
        ... )
        >>> session.browser
        'camoufox'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(description="Session identifier (UUID)")
    runner_id: str = Field(min_length=1, description="Runner that owns the session")
    status: SessionStatus = Field(description="Lifecycle state of the session")
    created_at: datetime = Field(description="Creation timestamp (UTC)")
    last_seen_at: datetime = Field(
        description="Last update timestamp (UTC)",
        validation_alias=AliasChoices("last_seen_at", "updated_at"),
        serialization_alias="last_seen_at",
    )
    ended_at: datetime | None = Field(
        default=None,
        description="Completion timestamp if available",
    )
    start_url: AnyUrl | None = Field(default=None, description="Initial page loaded in the browser")
    start_url_wait: StartUrlWait = Field(
        default=StartUrlWait.LOAD,
        description="Runner wait strategy for the optional start URL",
    )
    headless: bool = Field(
        default=False,
        description="Run the session without an attached VNC preview",
    )
    idle_ttl_seconds: PositiveInt = Field(
        default=300,
        ge=30,
        le=3600,
        description="Idle timeout for the session in seconds (30-3600)",
    )
    browser: str = Field(
        default="camoufox",
        min_length=1,
        description="Browser engine serving the session",
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="User-supplied labels propagated to Gateway/UI",
    )
    ws_endpoint: str | None = Field(
        default=None,
        description="Public WebSocket endpoint for control traffic",
        min_length=1,
    )
    proxy: SessionProxySettings | None = Field(
        default=None, description="Session-specific proxy configuration",
    )
    vnc: SessionVncDetails | None = Field(
        default=None,
        description="VNC connection details exposed to UI clients",
    )
    vnc_enabled: bool | None = Field(
        default=None,
        description="Whether the session currently exposes a VNC preview",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata replicated to UI/Gateway consumers",
    )

    @field_validator("runner_id")
    @classmethod
    def _trim_runner_id(cls, value: str) -> str:
        """Normalise the ``runner_id`` string before persistence.

        Args:
            value: Raw runner identifier supplied by the runner service.

        Returns:
            str: The trimmed identifier.

        Raises:
            ValueError: If the identifier is empty after trimming.

        Example:
            >>> Session._trim_runner_id(" runner-1 ")
            'runner-1'
        """

        trimmed = value.strip()
        if not trimmed:
            raise ValueError("runner_id must not be empty or whitespace only")
        return trimmed

    @field_validator("browser")
    @classmethod
    def _trim_browser(cls, value: str) -> str:
        """Normalise browser identifiers returned by runners.

        Args:
            value: Browser identifier string.

        Returns:
            str: Trimmed browser identifier.

        Raises:
            ValueError: If the identifier is empty after trimming.

        Example:
            >>> Session._trim_browser(" camoufox ")
            'camoufox'
        """

        trimmed = value.strip()
        if not trimmed:
            raise ValueError("browser must not be empty")
        return trimmed

    @field_validator("ws_endpoint")
    @classmethod
    def _clean_ws_endpoint(cls, value: str | None) -> str | None:
        """Normalise optional WebSocket endpoints prior to validation.

        Args:
            value: Raw endpoint string provided by the runner.

        Returns:
            str | None: Trimmed endpoint or ``None`` when absent.

        Raises:
            ValueError: If the endpoint is blank after trimming.

        Example:
            >>> Session._clean_ws_endpoint("  /sessions/1/ws  ")
            '/sessions/1/ws'
        """

        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("ws_endpoint must not be blank when provided")
        return trimmed

    @field_validator("labels")
    @classmethod
    def _validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        """Ensure label keys are meaningful and values coerced to strings.

        Args:
            value: Arbitrary mapping provided by upstream services.

        Returns:
            dict[str, str]: Sanitised mapping with trimmed keys and values.

        Raises:
            ValueError: If a label key is empty after trimming.

        Example:
            >>> Session._validate_labels({" env ": " staging "})
            {'env': 'staging'}
        """

        cleaned: dict[str, str] = {}
        for key, raw_value in value.items():
            key_str = str(key).strip()
            value_str = str(raw_value).strip()
            if not key_str:
                raise ValueError("label keys must be non-empty")
            cleaned[key_str] = value_str
        return cleaned

    @model_validator(mode="after")
    def _validate_temporal_relationships(self) -> "Session":
        """Assert time fields are ordered and timezone-aware.

        Returns:
            Session: The validated session instance.

        Raises:
            ValueError: If any timestamp lacks timezone info, ``last_seen_at`` is
                before ``created_at``, or ``ended_at`` precedes ``created_at``.

        Example:
            >>> session = build_session()  # doctest: +SKIP
            >>> session.last_seen_at >= session.created_at
            True
        """

        for attribute_name in ("created_at", "last_seen_at", "ended_at"):
            timestamp = getattr(self, attribute_name)
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError(f"{attribute_name} must be timezone-aware")

        if self.last_seen_at < self.created_at:
            raise ValueError("last_seen_at must be greater than or equal to created_at")

        if self.ended_at is not None and self.ended_at < self.created_at:
            raise ValueError("ended_at cannot be before created_at")

        return self

    @property
    def updated_at(self) -> datetime:
        """Backwards compatible alias for :attr:`last_seen_at`.

        Returns:
            datetime: Timestamp of the last heartbeat received for the session.

        Example:
            >>> session = Session(...).model_copy(update={})  # doctest: +SKIP
            >>> session.updated_at == session.last_seen_at
            True
        """

        return self.last_seen_at


class SessionEvent(BaseModel):
    """Event payload sent from runner to gateway and then to UI clients.

    Attributes:
        id: Unique identifier for the event (generated by the runner).
        type: Event type describing the nature of the change.
        session: Snapshot of the session after applying the change.
        occurred_at: Timestamp when the event was emitted.
        reason: Optional human-readable reason (e.g. failure cause).
        is_terminal: Convenience property returning ``True`` for terminal events.

    Example:
        >>> session = Session(
        ...     id=uuid4(),
        ...     runner_id="runner-1",
        ...     status=SessionStatus.INIT,
        ...     created_at=datetime.now(datetime.UTC),
        ...     last_seen_at=datetime.now(datetime.UTC),
        ...     headless=False,
        ...     idle_ttl_seconds=300,
        ... )
        >>> SessionEvent(session=session).type.value
        'session.updated'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4, description="Event identifier")
    type: SessionEventType = Field(default=SessionEventType.UPDATED, description="Event type")
    session: Session = Field(description="Session snapshot associated with the event")
    occurred_at: datetime = Field(description="Event emission timestamp (UTC)")
    reason: str | None = Field(default=None, description="Optional human-readable reason")

    @model_validator(mode="after")
    def _validate_event(self) -> "SessionEvent":
        """Validate event semantics for created and terminal events.

        Returns:
            SessionEvent: The validated event instance.

        Raises:
            ValueError: If ``occurred_at`` lacks timezone info, a CREATED event
                references a non-initial status, or an ENDED event does not
                point to a ``DEAD`` session.

        Example:
            >>> event = SessionEvent(
            ...     session=Session(...),  # doctest: +SKIP
            ...     occurred_at=datetime.now(datetime.UTC),
            ...     type=SessionEventType.CREATED,
            ... )
            >>> isinstance(event, SessionEvent)
            True
        """

        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        if self.type == SessionEventType.CREATED and self.session.status not in {
            SessionStatus.INIT,
            SessionStatus.READY,
        }:
            raise ValueError("created events must reference INIT or READY sessions")

        if self.type == SessionEventType.ENDED and self.session.status is not SessionStatus.DEAD:
            raise ValueError("ended events must reference DEAD sessions")

        return self

    @property
    def runner_id(self) -> str:
        """Return the identifier of the runner that emitted the event.

        Returns:
            str: Runner identifier copied from the underlying session snapshot.

        Example:
            >>> SessionEvent(session=Session(...)).runner_id  # doctest: +SKIP
            'runner-1'
        """

        return self.session.runner_id

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` when the event represents a fully terminated session.

        Returns:
            bool: ``True`` if the associated session status is :class:`SessionStatus.DEAD`.

        Example:
            >>> SessionEvent(session=Session(...)).is_terminal  # doctest: +SKIP
            False
        """

        return self.session.status is SessionStatus.DEAD


__all__ = [
    "Runner",
    "RunnerState",
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionProxySettings",
    "SessionStatus",
    "StartUrlWait",
    "SessionVncDetails",
]
