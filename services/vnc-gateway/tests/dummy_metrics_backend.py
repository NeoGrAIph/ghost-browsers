"""Test helpers exposing deterministic metrics backends."""

from __future__ import annotations

from camou_vnc_gateway.metrics import MetricEvent
from prometheus_client import CollectorRegistry

CUSTOM_REGISTRY = CollectorRegistry()


def get_registry() -> CollectorRegistry:
    """Return a shared :class:`CollectorRegistry` used in tests."""

    return CUSTOM_REGISTRY


class DummyOtlpExporter:
    """Collect metric events emitted through the OTLP backend."""

    def __init__(self) -> None:
        self.events: list[MetricEvent] = []

    def reset(self) -> None:
        """Remove previously captured events so tests start clean."""

        self.events.clear()

    def emit(self, event: MetricEvent) -> None:
        """Record an emitted metric event."""

        self.events.append(event)


DUMMY_EXPORTER = DummyOtlpExporter()


def get_exporter() -> DummyOtlpExporter:
    """Return the dummy exporter after clearing previous events."""

    DUMMY_EXPORTER.reset()
    return DUMMY_EXPORTER
