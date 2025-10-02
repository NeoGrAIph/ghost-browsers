"""Prometheus metric registry and descriptors for the runner service."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Summary

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


WORKSTATIONS_TOTAL_GAUGE = Gauge(
    "runner_workstations_total",
    "Total number of warm workstations managed by the pool.",
    registry=METRICS_REGISTRY,
)


WORKSTATIONS_IDLE_GAUGE = Gauge(
    "runner_workstations_idle",
    "Warm workstations currently available for reservation.",
    registry=METRICS_REGISTRY,
)


WORKSTATIONS_BUSY_GAUGE = Gauge(
    "runner_workstations_busy",
    "Warm workstations that are reserved, busy, or recycling.",
    registry=METRICS_REGISTRY,
)


WORKSTATIONS_ERROR_GAUGE = Gauge(
    "runner_workstations_error",
    "Warm workstations stuck in an error state requiring operator action.",
    registry=METRICS_REGISTRY,
)


WORKSTATION_RECYCLE_SECONDS = Histogram(
    "runner_workstation_recycle_seconds",
    "Time spent recycling a workstation back into the idle pool.",
    registry=METRICS_REGISTRY,
)


SESSION_ALLOCATE_SECONDS = Summary(
    "runner_session_allocate_seconds",
    "Latency of session allocation including warm pool reservation.",
    registry=METRICS_REGISTRY,
)


WORKSTATION_PROXY_ERRORS_COUNTER = Counter(
    "runner_workstation_proxy_errors_total",
    "Total number of workstation provisioning failures attributed to proxies.",
    registry=METRICS_REGISTRY,
)


WORKSTATION_NAVIGATION_ERRORS_COUNTER = Counter(
    "runner_workstation_navigation_errors_total",
    "Total number of prewarm navigation failures encountered by the pool.",
    registry=METRICS_REGISTRY,
)


__all__ = [
    "ACTIVE_SESSIONS_GAUGE",
    "METRICS_REGISTRY",
    "REAPER_EXPIRED_SESSIONS_COUNTER",
    "REAPER_LAST_RUN_GAUGE",
    "REAPER_RUNS_COUNTER",
    "SESSION_ALLOCATE_SECONDS",
    "VNC_ALLOCATION_REQUESTS_COUNTER",
    "VNC_ALLOCATIONS_GAUGE",
    "WORKSTATION_NAVIGATION_ERRORS_COUNTER",
    "WORKSTATION_PROXY_ERRORS_COUNTER",
    "WORKSTATION_RECYCLE_SECONDS",
    "WORKSTATIONS_BUSY_GAUGE",
    "WORKSTATIONS_ERROR_GAUGE",
    "WORKSTATIONS_IDLE_GAUGE",
    "WORKSTATIONS_TOTAL_GAUGE",
]
