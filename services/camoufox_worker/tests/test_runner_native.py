"""Tests for the native runner integration wrapper."""

from __future__ import annotations

import sys
import types
from typing import Any

# Provide lightweight stubs for the optional camoufox dependency when running tests.
if "camoufox" not in sys.modules:
    camoufox_module = types.ModuleType("camoufox")
    camoufox_sync_api_module = types.ModuleType("camoufox.sync_api")
    camoufox_errors_module = types.ModuleType("camoufox.errors")

    class _CamoufoxError(Exception):
        """Fallback Camoufox error stub for tests."""

    camoufox_errors_module.CamoufoxError = _CamoufoxError
    camoufox_sync_api_module.Camoufox = object  # type: ignore[assignment]

    camoufox_module.sync_api = camoufox_sync_api_module  # type: ignore[attr-defined]
    camoufox_module.errors = camoufox_errors_module  # type: ignore[attr-defined]

    sys.modules["camoufox"] = camoufox_module
    sys.modules["camoufox.sync_api"] = camoufox_sync_api_module
    sys.modules["camoufox.errors"] = camoufox_errors_module

from worker.jobs import Job, JobStatus
from worker.runner_native import run_job


class _DummyPage:
    """Minimal page stub mimicking Camoufox Page API."""

    def __init__(self, title: str) -> None:
        """Store the fake page title for later retrieval."""

        self._title = title
        self.last_url: str | None = None

    def goto(self, url: str) -> None:
        """Record navigation attempts for assertions."""

        self.last_url = url

    def title(self) -> str:
        """Return the stubbed page title."""

        return self._title


class _DummyCamoufox:
    """Context manager stub reproducing the Camoufox API surface."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Store configuration arguments (ignored) and prepare a stub page."""

        self.page = _DummyPage(title="Example Domain")

    def __enter__(self) -> "_DummyCamoufox":
        """Enter the context manager and return self."""

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
        """Propagate any raised exception to the caller."""

        return False

    def new_page(self) -> _DummyPage:
        """Return a preconfigured fake page."""

        return self.page


class _FailingCamoufox(_DummyCamoufox):
    """Context manager stub that raises to simulate runtime failures."""

    def __enter__(self) -> "_FailingCamoufox":
        """Simulate a failure on context entry to mimic runner errors."""

        raise RuntimeError("boom")


def test_run_job_returns_success_result(monkeypatch) -> None:
    """Return JobResult with success status and populated metrics."""

    monkeypatch.setattr("worker.runner_native.Camoufox", _DummyCamoufox)
    job = Job(url="https://example.com")

    result = run_job(job)

    assert result.ok is True
    assert result.status is JobStatus.SUCCESS
    assert result.title == "Example Domain"
    assert result.metrics.duration_ms >= 0
    assert result.error is None


def test_run_job_captures_errors(monkeypatch) -> None:
    """Translate runtime exceptions into failure JobResult instances."""

    monkeypatch.setattr("worker.runner_native.Camoufox", _FailingCamoufox)
    job = Job(url="https://example.com")

    result = run_job(job)

    assert result.ok is False
    assert result.status is JobStatus.FAILURE
    assert result.error is not None
    assert result.error.message == "boom"
