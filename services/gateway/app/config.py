"""Configuration helpers for the Gateway service."""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from core import Runner


@dataclass(slots=True)
class GatewaySettings:
    """Configuration object used to bootstrap the FastAPI application.

    Attributes:
        discovery_mode: Strategy for runner discovery (``static`` or ``dynamic``).
        discovery_endpoint: Optional HTTP endpoint returning the runner catalog
            when ``discovery_mode`` is set to ``http``.
        discovery_poll_interval_seconds: Interval between successive discovery
            and health maintenance iterations executed by the background task.
        runners: Initial list of runners that should be registered on startup.
        jwt_jwks_url: HTTP URL pointing to the Keycloak JWKS document.
        vnc_token_ttl_seconds: Lifetime of the issued VNC tokens in seconds.
        vnc_token_secret: Shared HMAC secret used for signing VNC JWT tokens.
        trusted_cidrs: Networks whose traffic is considered internal and bypasses
            bearer authentication.
        trusted_header: Optional header carrying the original caller IP placed by
            upstream ingress/sidecars.

    Example:
        >>> settings = GatewaySettings.from_env({
        ...     "RUNNERS": (
        ...         '[{"id": "r-1", "base_url": "http://runner", "total_slots": 1}]'
        ...     ),
        ...     "JWT_JWKS_URL": "http://idp.local/jwks",
        ...     "VNC_TOKEN_TTL_SEC": "120",
        ... })
        >>> settings.discovery_mode
        'static'
    """

    discovery_mode: str = "static"
    discovery_endpoint: str | None = None
    discovery_poll_interval_seconds: float = 10.0
    runners: list[Runner] = field(default_factory=list)
    jwt_jwks_url: str = "http://localhost/.well-known/jwks.json"
    vnc_token_ttl_seconds: int = 300
    vnc_token_secret: str = "dev-secret"
    trusted_cidrs: list[ipaddress._BaseNetwork] = field(default_factory=list)
    trusted_header: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GatewaySettings":
        """Create settings by reading the expected environment variables.

        Args:
            env: Optional mapping used during testing; defaults to :mod:`os.environ`.

        Returns:
            GatewaySettings: Populated settings instance.

        Raises:
            ValueError: If ``VNC_TOKEN_TTL_SEC`` is outside the allowed
                ``[1, 300]`` range, a runner definition cannot be parsed, or
                trusted CIDR/header variables contain invalid values.
        """

        env_map: Mapping[str, str] = os.environ if env is None else env
        defaults = cls()
        discovery_mode = env_map.get("DISCOVERY_MODE", defaults.discovery_mode)
        discovery_endpoint = env_map.get("DISCOVERY_ENDPOINT", defaults.discovery_endpoint)
        jwt_jwks_url = env_map.get("JWT_JWKS_URL", defaults.jwt_jwks_url)
        ttl_raw = env_map.get("VNC_TOKEN_TTL_SEC", str(defaults.vnc_token_ttl_seconds))
        ttl = int(ttl_raw)
        if ttl <= 0:
            raise ValueError("VNC_TOKEN_TTL_SEC must be between 1 and 300 seconds")
        if ttl > 300:
            raise ValueError("VNC_TOKEN_TTL_SEC must be between 1 and 300 seconds")
        poll_interval_raw = env_map.get(
            "DISCOVERY_POLL_INTERVAL_SEC",
            str(defaults.discovery_poll_interval_seconds),
        )
        poll_interval = float(poll_interval_raw)
        if poll_interval <= 0:
            raise ValueError("DISCOVERY_POLL_INTERVAL_SEC must be a positive number")
        runners = list(_parse_runners(env_map.get("RUNNERS")))
        trusted_cidrs = _parse_trusted_cidrs(env_map.get("GATEWAY_TRUSTED_CIDRS"))
        trusted_header = env_map.get("GATEWAY_TRUSTED_HEADER", defaults.trusted_header)
        if trusted_header is not None:
            trusted_header = trusted_header.strip() or None
        return cls(
            discovery_mode=discovery_mode,
            discovery_endpoint=discovery_endpoint,
            discovery_poll_interval_seconds=poll_interval,
            runners=runners,
            jwt_jwks_url=jwt_jwks_url,
            vnc_token_ttl_seconds=ttl,
            vnc_token_secret=env_map.get("VNC_TOKEN_SECRET", defaults.vnc_token_secret),
            trusted_cidrs=trusted_cidrs,
            trusted_header=trusted_header,
        )


def _parse_runners(raw: str | None) -> Iterable[Runner]:
    """Parse the ``RUNNERS`` environment variable into :class:`Runner` models.

    Args:
        raw: JSON string encoding a list of runner definitions. Each definition
            must match the :class:`Runner` schema from :mod:`core`.

    Yields:
        Runner: Validated runner instances ready to be registered.

    Raises:
        ValueError: If the payload cannot be parsed as JSON or does not contain a
            list of mapping objects.
    """

    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ValueError("RUNNERS must contain valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("RUNNERS must be a JSON array of runner objects")
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError("Runner definitions must be JSON objects")
        yield Runner.model_validate(item)


def _parse_trusted_cidrs(raw: str | None) -> list[ipaddress._BaseNetwork]:
    """Parse ``GATEWAY_TRUSTED_CIDRS`` into a list of IP networks.

    Args:
        raw: Comma-separated CIDR ranges to trust. Individual entries may contain
            whitespace which is ignored.

    Returns:
        list[ipaddress._BaseNetwork]: Networks parsed using :func:`ipaddress.ip_network`.

    Raises:
        ValueError: If an entry is empty or cannot be parsed as an IP network.

    Example:
        >>> _parse_trusted_cidrs("10.0.0.0/8, fd00::/64")
        [IPv4Network('10.0.0.0/8'), IPv6Network('fd00::/64')]
    """

    if raw is None or raw.strip() == "":
        return []
    networks: list[ipaddress._BaseNetwork] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            raise ValueError("GATEWAY_TRUSTED_CIDRS must not contain empty entries")
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"Invalid CIDR entry in GATEWAY_TRUSTED_CIDRS: {candidate}"
            ) from exc
        networks.append(network)
    return networks
