"""Tests for the native Camoufox runner integration wrapper."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from worker.jobs import Job, JobStatus
from worker.runner_native import run_job


class _RecordingPage:
    """Page stub that records navigation attempts and cleanup calls."""

    def __init__(self, title: str = "Example Domain") -> None:
        """Initialise the stubbed page with a predefined title."""

        self._title = title
        self.last_url: Optional[str] = None
        self.goto_kwargs: Dict[str, Any] | None = None
        self.closed = False

    def goto(self, url: str, **kwargs: Any) -> None:
        """Store the last navigated URL and keyword arguments."""

        self.last_url = url
        self.goto_kwargs = dict(kwargs)

    def title(self) -> str:
        """Return the configured fake page title."""

        return self._title

    def close(self) -> None:
        """Mark the page as closed for assertions."""

        self.closed = True


class _RecordingContext:
    """Camoufox context stub capturing options and lifecycle hooks."""

    def __init__(self, options: Dict[str, Any]) -> None:
        """Store context options and lazily create pages."""

        self.options = dict(options)
        self.pages: List[_RecordingPage] = []
        self.closed = False

    def new_page(self) -> _RecordingPage:
        """Return a new recording page and keep track of it."""

        page = _RecordingPage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        """Record that the context has been closed."""

        self.closed = True


class _RecordingCamoufox:
    """Context manager stub reproducing the Camoufox API surface."""

    instances: List["_RecordingCamoufox"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Store configuration arguments and prepare tracking containers."""

        self.args = args
        self.kwargs = dict(kwargs)
        self.contexts: List[_RecordingContext] = []
        self.pages: List[_RecordingPage] = []
        self.closed = False
        _RecordingCamoufox.instances.append(self)

    def __enter__(self) -> "_RecordingCamoufox":
        """Enter the context manager and return self."""

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
        """Mark the browser as closed and propagate exceptions."""

        self.closed = True
        return False

    def new_context(self, **kwargs: Any) -> _RecordingContext:
        """Create a new context recording the provided keyword arguments."""

        context = _RecordingContext(kwargs)
        self.contexts.append(context)
        return context

    def new_page(self, **kwargs: Any) -> _RecordingPage:
        """Fallback for environments lacking context support."""

        page = _RecordingPage()
        self.pages.append(page)
        return page


class _FailingCamoufox(_RecordingCamoufox):
    """Context manager stub that raises to simulate runtime failures."""

    def __enter__(self) -> "_FailingCamoufox":
        """Simulate a failure on context entry to mimic runner errors."""

        raise RuntimeError("boom")


def _reset_recording_state() -> None:
    """Clear accumulated stub instances between tests."""

    _RecordingCamoufox.instances.clear()


def test_run_job_returns_success_result(monkeypatch) -> None:
    """Return JobResult with success status, metrics and cleaned resources."""

    _reset_recording_state()
    monkeypatch.setattr("worker.runner_native.Camoufox", _RecordingCamoufox)
    monkeypatch.delenv("CAMOUFOX_HEADLESS", raising=False)
    job = Job(url="https://example.com")

    result = run_job(job)

    assert result.ok is True
    assert result.status is JobStatus.SUCCESS
    assert result.title == "Example Domain"
    assert result.metrics.extra["navigation_status"] == "success"

    browser = _RecordingCamoufox.instances[-1]
    assert browser.kwargs.get("headless") == "virtual"
    assert browser.closed is True
    assert browser.contexts[0].closed is True
    assert browser.contexts[0].pages[0].closed is True


def test_run_job_captures_errors(monkeypatch) -> None:
    """Translate runtime exceptions into failure JobResult instances."""

    _reset_recording_state()
    monkeypatch.setattr("worker.runner_native.Camoufox", _FailingCamoufox)
    job = Job(url="https://example.com")

    result = run_job(job)

    assert result.ok is False
    assert result.status is JobStatus.FAILURE
    assert result.error is not None
    assert result.error.message == "boom"
    assert result.metrics.extra["navigation_status"] == "context_failed"


def test_run_job_wires_proxy_and_timeout(monkeypatch) -> None:
    """Apply per-job proxy configuration and enforce navigation timeout."""

    _reset_recording_state()
    monkeypatch.setattr("worker.runner_native.Camoufox", _RecordingCamoufox)
    job = Job(
        url="https://example.com",
        http_proxy="http://user:pwd@localhost:8080",
        timeout_sec=42,
    )

    result = run_job(job)

    assert result.ok is True

    browser = _RecordingCamoufox.instances[-1]
    context = browser.contexts[0]
    assert context.options["proxy"]["server"] == "http://localhost:8080"
    assert context.options["proxy"]["username"] == "user"
    assert context.options["proxy"]["password"] == "pwd"

    page = context.pages[0]
    assert page.last_url == "https://example.com"
    assert page.goto_kwargs == {"timeout": 42000}
    assert result.metrics.extra["timeout_ms"] == 42000.0
