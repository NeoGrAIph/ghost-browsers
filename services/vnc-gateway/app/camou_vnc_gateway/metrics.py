"""Metrics helpers for the VNC gateway service.

The module provides two complementary building blocks that keep the proxy
observable without introducing external dependencies:

* :class:`ConnectionRegistry` – an async context manager that mirrors the
  amount of in-flight HTTP and WebSocket connections and exposes those numbers
  both via structured logs and backend agnostic counters, and
* :func:`record_token_validation_failure` – a lightweight hook that surfaces
  token verification errors so operators can correlate spikes with
  authentication misconfigurations.

Metric storage backends are configured at runtime.  By default the service uses
an in-process :class:`prometheus_client.CollectorRegistry`, but settings can
point to an existing registry or an OpenTelemetry/OTLP exporter.  The
``/metrics`` endpoint (see ``camou_vnc_gateway.routes``) exposes Prometheus
payloads when such a backend is configured.  Tests may import the symbols
defined here to assert on metric values without having to spin up additional
infrastructure.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client import Counter as PromCounter
from prometheus_client.exposition import CONTENT_TYPE_LATEST

LOG = logging.getLogger(__name__)

METRICS_NAMESPACE = "camou_vnc_gateway"


@dataclass(frozen=True, slots=True)
class MetricEvent:
    """Structured representation of metric changes emitted to exporters.

    Attributes
    ----------
    name:
        Canonical metric identifier (without namespace prefix).  The helper
        functions in this module use ``active_connections`` and
        ``connection_opens_total`` among others.
    value:
        Numeric value associated with the metric update.  Counters always emit
        positive increments while gauges can report absolute values.
    attributes:
        Dimensional labels attached to the metric sample.
    kind:
        Type discriminator describing how the exporter should treat ``value``.
        ``"counter"`` indicates a monotonically increasing series, whereas
        ``"gauge"`` describes instantaneous values that can go up and down.
    """

    name: str
    value: float
    attributes: dict[str, str]
    kind: str


@runtime_checkable
class MetricsEventExporter(Protocol):
    """Protocol implemented by OTLP exporters used by the gateway.

    Exporters only need to expose a single :meth:`emit` method because the
    gateway produces a very small set of events.  Implementations may batch
    events, forward them to OpenTelemetry SDKs or simply store them in memory
    for assertions in unit tests.
    """

    def emit(self, event: MetricEvent) -> None:
        """Consume a :class:`MetricEvent` produced by the service."""


class MetricsRenderNotSupportedError(RuntimeError):
    """Raised when the active metrics backend cannot render Prometheus output."""


class NoopEventExporter:
    """Fallback exporter that silently drops OTLP events.

    The class is intentionally minimal because production deployments are
    expected to provide a concrete exporter.  Keeping a no-op implementation
    allows unit tests to configure the OTLP backend without additional
    dependencies.
    """

    def emit(self, event: MetricEvent) -> None:  # pragma: no cover - trivial
        """Ignore emitted events."""


class BaseMetricsBackend:
    """Common functionality shared by metrics backends."""

    registry: CollectorRegistry | None

    def increment_connection_opens(self, *, channel: str) -> None:
        """Record a connection open event for the provided channel."""

    def set_active_connections(self, *, session_id: str, channel: str, value: int) -> None:
        """Publish the current number of active connections for a session."""

    def remove_active_connections(self, *, session_id: str, channel: str) -> None:
        """Remove the active connection time-series for the provided labels."""

    def record_token_validation_failure(self, *, reason: str) -> None:
        """Increment the validation failure counter for ``reason``."""

    def render(self) -> tuple[bytes, str] | None:
        """Return an HTTP payload if the backend supports Prometheus exposition."""


class PrometheusMetricsBackend(BaseMetricsBackend):
    """Prometheus implementation backed by :class:`CollectorRegistry`."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._active_connections = Gauge(
            f"{METRICS_NAMESPACE}_active_connections",
            "Number of active proxied connections grouped by session and channel.",
            ("session_id", "channel"),
            registry=self.registry,
        )
        self._connection_open_total = PromCounter(
            f"{METRICS_NAMESPACE}_connection_opens_total",
            "Total number of proxied connections opened per channel.",
            ("channel",),
            registry=self.registry,
        )
        self._token_validation_failures = PromCounter(
            f"{METRICS_NAMESPACE}_token_validation_failures_total",
            "Count of rejected VNC tokens partitioned by failure reason.",
            ("reason",),
            registry=self.registry,
        )

    def increment_connection_opens(self, *, channel: str) -> None:
        self._connection_open_total.labels(channel=channel).inc()

    def set_active_connections(self, *, session_id: str, channel: str, value: int) -> None:
        self._active_connections.labels(session_id=session_id, channel=channel).set(value)

    def remove_active_connections(self, *, session_id: str, channel: str) -> None:
        with suppress(KeyError):
            self._active_connections.remove(session_id, channel)

    def record_token_validation_failure(self, *, reason: str) -> None:
        self._token_validation_failures.labels(reason=reason).inc()

    def render(self) -> tuple[bytes, str]:
        payload = generate_latest(self.registry)
        return payload, CONTENT_TYPE_LATEST


class OtlpMetricsBackend(BaseMetricsBackend):
    """Adapter that forwards metric events to an OTLP exporter."""

    def __init__(self, exporter: MetricsEventExporter | None = None) -> None:
        self.registry = None
        self._exporter = exporter or NoopEventExporter()

    def increment_connection_opens(self, *, channel: str) -> None:
        self._exporter.emit(
            MetricEvent(
                name=f"{METRICS_NAMESPACE}_connection_opens_total",
                value=1.0,
                attributes={"channel": channel},
                kind="counter",
            )
        )

    def set_active_connections(self, *, session_id: str, channel: str, value: int) -> None:
        self._exporter.emit(
            MetricEvent(
                name=f"{METRICS_NAMESPACE}_active_connections",
                value=float(value),
                attributes={"session_id": session_id, "channel": channel},
                kind="gauge",
            )
        )

    def remove_active_connections(self, *, session_id: str, channel: str) -> None:
        self._exporter.emit(
            MetricEvent(
                name=f"{METRICS_NAMESPACE}_active_connections",
                value=0.0,
                attributes={"session_id": session_id, "channel": channel},
                kind="gauge",
            )
        )

    def record_token_validation_failure(self, *, reason: str) -> None:
        self._exporter.emit(
            MetricEvent(
                name=f"{METRICS_NAMESPACE}_token_validation_failures_total",
                value=1.0,
                attributes={"reason": reason},
                kind="counter",
            )
        )

    def render(self) -> tuple[bytes, str] | None:  # pragma: no cover - defensive
        return None


_METRICS_BACKEND: BaseMetricsBackend = PrometheusMetricsBackend()

# ``METRICS_REGISTRY`` is kept for backwards compatibility with the original
# implementation.  It is ``None`` when the service is configured to use
# alternative exporters.
METRICS_REGISTRY: CollectorRegistry | None = _METRICS_BACKEND.registry


def _set_metrics_backend(backend: BaseMetricsBackend) -> None:
    """Swap the module-level metrics backend.

    Parameters
    ----------
    backend:
        Backend implementation that should become the new default.
    """

    global _METRICS_BACKEND, METRICS_REGISTRY
    _METRICS_BACKEND = backend
    METRICS_REGISTRY = backend.registry


def get_metrics_backend() -> BaseMetricsBackend:
    """Return the active metrics backend used by the service."""

    return _METRICS_BACKEND


def configure_metrics_backend(backend: BaseMetricsBackend) -> BaseMetricsBackend:
    """Install ``backend`` as the process-wide metrics backend.

    The function returns the provided backend so callers can chain the
    configuration and re-use the instance, e.g.::

        backend = configure_metrics_backend(PrometheusMetricsBackend())
        registry = ConnectionRegistry(metrics=backend)

    Parameters
    ----------
    backend:
        Backend implementation that should be used by subsequent metric calls.

    Returns
    -------
    BaseMetricsBackend
        The provided backend instance.
    """

    _set_metrics_backend(backend)
    return backend


def _import_from_string(path: str) -> Any:
    """Import an object from ``path`` supporting ``module:attr`` syntax."""

    module_path, _, attr = path.replace("::", ":").rpartition(":")
    if not module_path:
        module_path, _, attr = path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid import string: {path}")
    module = import_module(module_path)
    target = getattr(module, attr)
    return target


def _resolve_prometheus_registry(path: str | None) -> CollectorRegistry:
    """Return a :class:`CollectorRegistry` defined by ``path`` or a new instance."""

    if not path:
        return CollectorRegistry()
    target = _import_from_string(path)
    registry = target() if callable(target) else target
    if not isinstance(registry, CollectorRegistry):  # pragma: no cover - guard rail
        raise TypeError("Configured metrics registry is not a CollectorRegistry instance")
    return registry


def _resolve_otlp_exporter(path: str | None) -> MetricsEventExporter:
    """Import an OTLP exporter callable from ``path`` or fallback to noop."""

    if not path:
        return NoopEventExporter()
    target = _import_from_string(path)
    exporter = target() if callable(target) else target
    if not isinstance(exporter, MetricsEventExporter):  # pragma: no cover - guard rail
        raise TypeError("Configured OTLP exporter does not implement MetricsEventExporter")
    return exporter


def build_metrics_backend_from_settings(settings: Any) -> BaseMetricsBackend:
    """Create a metrics backend based on the supplied settings object.

    Parameters
    ----------
    settings:
        Instance of :class:`camou_vnc_gateway.config.Settings` or a compatible
        object exposing ``metrics_backend``, ``metrics_registry_import`` and
        ``metrics_otlp_exporter_import`` attributes.
    """

    backend_kind = getattr(settings, "metrics_backend", "prometheus")
    if backend_kind == "prometheus":
        registry_path = getattr(settings, "metrics_registry_import", None)
        registry = _resolve_prometheus_registry(registry_path)
        return PrometheusMetricsBackend(registry)
    if backend_kind == "otlp":
        exporter_path = getattr(settings, "metrics_otlp_exporter_import", None)
        exporter = _resolve_otlp_exporter(exporter_path)
        return OtlpMetricsBackend(exporter)
    raise ValueError(f"Unsupported metrics backend: {backend_kind}")


class ConnectionRegistry:
    """Track active HTTP and WebSocket connections per session.

    The registry is intentionally simple: it stores counters in-memory and
    relies on cooperative scheduling through :mod:`asyncio`.  This suffices for
    unit tests and local development where the process lifetime is short-lived
    and the set of tracked sessions is limited.
    """

    def __init__(self, *, metrics: BaseMetricsBackend | None = None) -> None:
        """Initialise the registry.

        Parameters
        ----------
        metrics:
            Optional metrics backend to use.  When omitted the module-level
            backend configured through :func:`configure_metrics_backend` is
            reused.
        """

        self._lock = asyncio.Lock()
        self._active = Counter()
        self._metrics = metrics or get_metrics_backend()

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
            self._metrics.increment_connection_opens(channel=channel)
            self._metrics.set_active_connections(
                session_id=session_id, channel=channel, value=active
            )
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
                    self._metrics.remove_active_connections(
                        session_id=session_id, channel=channel
                    )
                    if active < 0:
                        self._active[key] = 0
                else:
                    self._metrics.set_active_connections(
                        session_id=session_id, channel=channel, value=active
                    )

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

    get_metrics_backend().record_token_validation_failure(reason=reason)


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Return the current Prometheus exposition payload and content type.

    Raises
    ------
    MetricsRenderNotSupportedError
        Raised when the active backend does not provide a Prometheus registry.
    """

    payload = _METRICS_BACKEND.render()
    if payload is None:
        raise MetricsRenderNotSupportedError("Prometheus exporter is not configured")
    return payload


__all__ = [
    "BaseMetricsBackend",
    "ConnectionRegistry",
    "METRICS_REGISTRY",
    "MetricEvent",
    "MetricsEventExporter",
    "MetricsRenderNotSupportedError",
    "OtlpMetricsBackend",
    "PrometheusMetricsBackend",
    "build_metrics_backend_from_settings",
    "configure_metrics_backend",
    "get_metrics_backend",
    "record_token_validation_failure",
    "render_prometheus_metrics",
]
