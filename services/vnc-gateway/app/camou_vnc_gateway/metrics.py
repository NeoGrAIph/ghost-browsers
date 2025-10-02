"""Metrics helpers for the VNC gateway service.

The module provides two complementary building blocks that keep the proxy
observable without introducing external dependencies:

* :class:`ConnectionRegistry` – an async context manager that mirrors the
  amount of in-flight HTTP and WebSocket connections and exposes those numbers
  both via structured logs and Prometheus gauges/counters, and
* :func:`record_token_validation_failure` – a lightweight hook that surfaces
  token verification errors as Prometheus counters so operators can correlate
  spikes with authentication misconfigurations.

Metrics are stored in a process-wide :class:`prometheus_client.CollectorRegistry`
instance and exported through the ``/metrics`` endpoint (see
``camou_vnc_gateway.routes``).  Tests may import the symbols defined here to
assert on metric values without having to spin up a full Prometheus registry.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from prometheus_client import CollectorRegistry, Counter as PromCounter
from prometheus_client import Gauge, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST

LOG = logging.getLogger(__name__)

# Dedicated registry so tests can assert against a deterministic metrics set and
# to avoid global Prometheus state leaking in multi-service test suites.
METRICS_REGISTRY = CollectorRegistry()

_ACTIVE_CONNECTIONS = Gauge(
    "camou_vnc_gateway_active_connections",
    "Number of active proxied connections grouped by session and channel.",
    ("session_id", "channel"),
    registry=METRICS_REGISTRY,
)

_CONNECTION_OPEN_TOTAL = PromCounter(
    "camou_vnc_gateway_connection_opens_total",
    "Total number of proxied connections opened per channel.",
    ("channel",),
    registry=METRICS_REGISTRY,
)

_TOKEN_VALIDATION_FAILURES = PromCounter(
    "camou_vnc_gateway_token_validation_failures_total",
    "Count of rejected VNC tokens partitioned by failure reason.",
    ("reason",),
    registry=METRICS_REGISTRY,
)


class ConnectionRegistry:
    """Track active HTTP and WebSocket connections per session.

    The registry is intentionally simple: it stores counters in-memory and
    relies on cooperative scheduling through :mod:`asyncio`.  This suffices for
    unit tests and local development where the process lifetime is short-lived
    and the set of tracked sessions is limited.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = Counter()

    @asynccontextmanager
    async def track(self, *, session_id: str, channel: str) -> AsyncIterator[None]:
        """Context manager used to track a proxied connection lifecycle.

        Parameters
        ----------
        session_id:
            Identifier of the session currently being proxied.
        channel:
            Human readable channel label (e.g. ``"http"`` or ``"ws"``).
        """

        key = (session_id, channel)
        async with self._lock:
            self._active[key] += 1
            active = self._active[key]
            LOG.info(
                "connection.started",
                extra={"session_id": session_id, "channel": channel, "active": active},
            )
            _CONNECTION_OPEN_TOTAL.labels(channel=channel).inc()
            _ACTIVE_CONNECTIONS.labels(session_id=session_id, channel=channel).set(active)
        try:
            yield
        finally:
            async with self._lock:
                self._active[key] -= 1
                active = self._active[key]
                LOG.info(
                    "connection.finished",
                    extra={
                        "session_id": session_id,
                        "channel": channel,
                        "active": active,
                    },
                )
                if active <= 0:
                    # Remove labels entirely to prevent Prometheus from
                    # reporting inactive time-series indefinitely.
                    with suppress(KeyError):
                        _ACTIVE_CONNECTIONS.remove(session_id, channel)
                    if active < 0:
                        self._active[key] = 0
                else:
                    _ACTIVE_CONNECTIONS.labels(session_id=session_id, channel=channel).set(active)

    async def snapshot(self) -> dict[tuple[str, str], int]:
        """Return a shallow copy of the current counter state."""

        async with self._lock:
            return dict(self._active)


def record_token_validation_failure(*, reason: str) -> None:
    """Increment the validation failure counter for the provided reason.

    Parameters
    ----------
    reason:
        Human readable error description (typically derived from
        :class:`TokenValidationError`).  Values should be coarse-grained to
        avoid high-cardinality metrics.
    """

    _TOKEN_VALIDATION_FAILURES.labels(reason=reason).inc()


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Return the current Prometheus exposition payload and content type."""

    payload = generate_latest(METRICS_REGISTRY)
    return payload, CONTENT_TYPE_LATEST


__all__ = [
    "ConnectionRegistry",
    "METRICS_REGISTRY",
    "record_token_validation_failure",
    "render_prometheus_metrics",
]
