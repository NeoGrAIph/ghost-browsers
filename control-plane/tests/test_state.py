from __future__ import annotations

import pytest

from camofleet_control.config import ControlSettings, WorkerConfig
from camofleet_control.main import (
    AppState,
    build_public_ws_endpoint,
    build_worker_ws_endpoint,
    normalise_public_prefix,
)
from fastapi import HTTPException


def make_settings(workers: list[WorkerConfig]) -> ControlSettings:
    return ControlSettings(workers=workers)


def test_pick_worker_round_robin() -> None:
    workers = [
        WorkerConfig(name="a", url="http://a"),
        WorkerConfig(name="b", url="http://b"),
    ]
    state = AppState(make_settings(workers))
    assert state.pick_worker().name == "a"
    assert state.pick_worker().name == "b"
    assert state.pick_worker().name == "a"


def test_pick_worker_by_name() -> None:
    workers = [WorkerConfig(name="x", url="http://x")]
    state = AppState(make_settings(workers))
    assert state.pick_worker("x").name == "x"
    with pytest.raises(HTTPException):
        state.pick_worker("missing")


def test_pick_worker_requires_vnc() -> None:
    workers = [
        WorkerConfig(name="headless", url="http://a", supports_vnc=False),
        WorkerConfig(name="vnc", url="http://b", supports_vnc=True),
    ]
    state = AppState(make_settings(workers))
    assert state.pick_worker(require_vnc=True).name == "vnc"
    with pytest.raises(HTTPException):
        state.pick_worker("headless", require_vnc=True)


def test_normalise_public_prefix() -> None:
    assert normalise_public_prefix("/") == ""
    assert normalise_public_prefix("/api/") == "/api"
    assert normalise_public_prefix("api") == "/api"
    assert normalise_public_prefix("") == ""


def test_build_public_ws_endpoint() -> None:
    settings = ControlSettings(public_api_prefix="/api")
    assert (
        build_public_ws_endpoint(settings, "worker-1", "session-1")
        == "/api/sessions/worker-1/session-1/ws"
    )
    settings = ControlSettings(public_api_prefix="/")
    assert (
        build_public_ws_endpoint(settings, "worker-2", "session-2")
        == "/sessions/worker-2/session-2/ws"
    )


def test_build_worker_ws_endpoint() -> None:
    worker = WorkerConfig(name="a", url="http://worker:8080")
    assert (
        build_worker_ws_endpoint(worker, "sess")
        == "ws://worker:8080/sessions/sess/ws"
    )
    worker = WorkerConfig(name="b", url="https://worker.example")
    assert (
        build_worker_ws_endpoint(worker, "sess")
        == "wss://worker.example/sessions/sess/ws"
    )
    worker = WorkerConfig(name="c", url="https://worker.example/prefix")
    assert (
        build_worker_ws_endpoint(worker, "sess")
        == "wss://worker.example/prefix/sessions/sess/ws"
    )
