"""Tests covering the Click-based CLI entrypoint for the worker."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Dict

import pytest

from worker import main as worker_main
from worker.jobs import Job, JobError, JobMetrics, JobResult, JobStatus


def _make_result(*, job: Job, ok: bool) -> JobResult:
    """Construct a ``JobResult`` instance with consistent timestamps."""

    started = datetime.now(UTC)
    finished = started + timedelta(seconds=1)
    status = JobStatus.SUCCESS if ok else JobStatus.FAILURE
    error = None if ok else JobError(type="RuntimeError", message="failure")
    return JobResult(
        job=job,
        status=status,
        ok=ok,
        started_at=started,
        finished_at=finished,
        metrics=JobMetrics(duration_ms=1000),
        error=error,
    )


def test_main_runs_native_mode_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Invoke the CLI in native mode and emit a success payload to stdout."""

    captured: Dict[str, Any] = {}

    def _fake_run_job(job: Job) -> JobResult:
        captured["job"] = job
        return _make_result(job=job, ok=True)

    monkeypatch.setattr(worker_main, "run_job", _fake_run_job)

    exit_code = worker_main.main(["run", "--url", "https://example.com", "--timeout", "30"])

    assert exit_code == 0
    assert isinstance(captured["job"], Job)
    assert captured["job"].timeout_sec == 30

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"


def test_main_uses_env_defaults_for_orchestrator(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Respect environment-provided mode and gateway configuration for orchestrator runs."""

    monkeypatch.setenv("WORKER_MODE", "orchestrator")
    monkeypatch.setenv("GATEWAY_URL", "https://gateway")
    monkeypatch.setenv("GATEWAY_TOKEN", "token")

    calls: Dict[str, Any] = {}

    async def _fake_run_orchestrator(*args: Any, **kwargs: Any) -> JobResult:
        calls["args"] = args
        calls["kwargs"] = kwargs
        job_arg = args[0]
        return _make_result(job=job_arg, ok=True)

    monkeypatch.setattr(worker_main, "_run_orchestrator", _fake_run_orchestrator)
    monkeypatch.setattr(worker_main, "run_job", lambda job: pytest.fail("native runner should not be used"))

    exit_code = worker_main.main(["run", "--url", "https://example.com"])

    assert exit_code == 0
    assert isinstance(calls["args"][0], Job)
    assert str(calls["args"][0].url) == "https://example.com/"
    assert calls["kwargs"]["gateway_url"] == "https://gateway"
    assert calls["kwargs"]["gateway_token"] == "token"

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"


def test_main_requires_gateway_credentials_for_orchestrator(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Exit with an error when orchestrator mode lacks gateway configuration."""

    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)

    exit_code = worker_main.main(["run", "--url", "https://example.com", "--mode", "orchestrator"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Gateway URL" in captured.err


def test_main_propagates_failure_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Return a non-zero exit code when the job result signals failure."""

    def _fake_run_job(job: Job) -> JobResult:
        return _make_result(job=job, ok=False)

    monkeypatch.setattr(worker_main, "run_job", _fake_run_job)

    exit_code = worker_main.main(["run", "--url", "https://example.com"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failure"
