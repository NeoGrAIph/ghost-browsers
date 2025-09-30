import pytest

from camofleet_control.config import WorkerConfig
from camofleet_control.main import apply_vnc_overrides


@pytest.fixture(name="worker")
def fixture_worker() -> WorkerConfig:
    return WorkerConfig(
        name="worker-vnc",
        url="http://worker",
        supports_vnc=True,
        vnc_http="https://public.example/vnc/{id}",
        vnc_ws="wss://public.example/websockify?token={id}",
    )


def test_apply_vnc_overrides_merges_paths_and_query(worker: WorkerConfig) -> None:
    payload = {
        "http": "http://127.0.0.1:6930/vnc.html?path=websockify&target_port=6930",
        "ws": "ws://127.0.0.1:6930/websockify?target_port=6930",
        "password_protected": False,
    }

    result = apply_vnc_overrides(worker, "session-123", payload)

    assert result["http"] == (
        "https://public.example/vnc/session-123/vnc.html?path=websockify&target_port=6930"
    )
    assert result["ws"] == (
        "wss://public.example/websockify?token=session-123&target_port=6930"
    )
    assert result["password_protected"] is False


def test_apply_vnc_overrides_handles_missing_payload(worker: WorkerConfig) -> None:
    result = apply_vnc_overrides(worker, "session-456", None)

    assert result == {}


def test_apply_vnc_overrides_treats_falsy_endpoints_as_missing(
    worker: WorkerConfig,
) -> None:
    payload = {"http": None, "ws": None, "password_protected": False}

    result = apply_vnc_overrides(worker, "session-457", payload)

    assert result == {}


def test_apply_vnc_overrides_preserves_target_port(worker: WorkerConfig) -> None:
    payload = {
        # Runner originally builds this from a loopback URL without ``target_port``;
        # ensure we surface the propagated value after overrides are applied.
        "http": "http://127.0.0.1:6930/vnc.html?path=websockify&target_port=6930",
        "ws": "ws://127.0.0.1:6930/websockify?target_port=6930",
        "password_protected": False,
    }

    result = apply_vnc_overrides(worker, "session-789", payload)

    assert result["http"] == (
        "https://public.example/vnc/session-789/vnc.html?path=websockify&target_port=6930"
    )
    assert result["ws"] == (
        "wss://public.example/websockify?token=session-789&target_port=6930"
    )


def test_apply_vnc_overrides_avoids_duplicate_segments(worker: WorkerConfig) -> None:
    payload = {
        "http": "http://127.0.0.1:6930/vnc/vnc.html?path=vnc/websockify&target_port=6930",
        "ws": "ws://127.0.0.1:6930/vnc/websockify?target_port=6930",
    }

    result = apply_vnc_overrides(worker, "session-246", payload)

    assert result["http"] == (
        "https://public.example/vnc/session-246/vnc.html?path=vnc%2Fwebsockify&target_port=6930"
    )
    assert result["ws"] == (
        "wss://public.example/websockify?token=session-246&target_port=6930"
    )


def test_apply_vnc_overrides_matches_helm_defaults() -> None:
    worker = WorkerConfig(
        name="worker-vnc",
        url="http://worker-vnc",  # matches the service endpoint rendered by Helm
        supports_vnc=True,
        vnc_http="http://camofleet-worker-vnc:6080/vnc/{id}",
        vnc_ws="ws://camofleet-worker-vnc:6080/websockify?token={id}",
    )

    payload = {
        "http": "http://127.0.0.1:6930/vnc/vnc.html?path=vnc/websockify&target_port=6930",
        "ws": "ws://127.0.0.1:6930/vnc/websockify?target_port=6930",
    }

    result = apply_vnc_overrides(worker, "session-helm", payload)

    assert result["http"] == (
        "http://camofleet-worker-vnc:6080/"
        "vnc/session-helm/vnc.html?path=vnc%2Fwebsockify&target_port=6930"
    )
    assert result["ws"] == (
        "ws://camofleet-worker-vnc:6080/"
        "websockify?token=session-helm&target_port=6930"
    )
