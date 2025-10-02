"""Prometheus metric registry and descriptors for the runner service."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge

METRICS_REGISTRY = CollectorRegistry()


ACTIVE_SESSIONS_GAUGE = Gauge(
    "runner_active_sessions",
    "Number of sessions that are currently not in the DEAD state.",
    registry=METRICS_REGISTRY,
)


REAPER_RUNS_COUNTER = Counter(
    "runner_reaper_runs_total",
    "Total number of idle reaper sweeps executed by the runner.",
    registry=METRICS_REGISTRY,
)


REAPER_EXPIRED_SESSIONS_COUNTER = Counter(
    "runner_reaper_expired_sessions_total",
    "Total sessions terminated due to idle timeouts.",
    registry=METRICS_REGISTRY,
)


REAPER_LAST_RUN_GAUGE = Gauge(
    "runner_reaper_last_run_timestamp",
    "Unix timestamp of the most recent idle reaper execution.",
    registry=METRICS_REGISTRY,
)


VNC_ALLOCATIONS_GAUGE = Gauge(
    "runner_vnc_allocations",
    "Number of active VNC allocations maintained by the runner.",
    registry=METRICS_REGISTRY,
)


VNC_ALLOCATION_REQUESTS_COUNTER = Counter(
    "runner_vnc_allocation_requests_total",
    "Total VNC helper allocations requested from the controller.",
    registry=METRICS_REGISTRY,
)


__all__ = [
    "ACTIVE_SESSIONS_GAUGE",
    "METRICS_REGISTRY",
    "REAPER_EXPIRED_SESSIONS_COUNTER",
    "REAPER_LAST_RUN_GAUGE",
    "REAPER_RUNS_COUNTER",
    "VNC_ALLOCATION_REQUESTS_COUNTER",
    "VNC_ALLOCATIONS_GAUGE",
]
