from urllib.parse import parse_qs, urlparse

import pytest

from camoufox_runner.sessions import SessionManager


@pytest.fixture(name="manager")
def fixture_manager() -> SessionManager:
    # ``_compose_public_url`` does not depend on initialised state, therefore we
    # can instantiate the object without running ``__init__``.
    return SessionManager.__new__(SessionManager)  # type: ignore[call-arg]


def test_compose_public_url_with_dynamic_ports(manager: SessionManager) -> None:
    result = manager._compose_public_url(
        "http://localhost:6900",
        6930,
        "/vnc.html",
        query_params={"path": "websockify"},
    )

    assert result == "http://localhost:6930/vnc.html?path=websockify&target_port=6930"


def test_compose_public_url_adds_target_when_query_absent(manager: SessionManager) -> None:
    result = manager._compose_public_url(
        "http://localhost:6900",
        6930,
        "/websockify",
    )

    assert result == "http://localhost:6930/websockify?target_port=6930"


def test_compose_public_url_adds_target_when_missing_in_base_query(
    manager: SessionManager,
) -> None:
    result = manager._compose_public_url(
        "http://localhost:6900?foo=bar",
        6930,
        "/vnc.html",
        query_params={"path": "websockify"},
    )

    parsed = urlparse(result)
    query = parse_qs(parsed.query)
    assert query["foo"] == ["bar"]
    assert query["path"] == ["websockify"]
    assert query["target_port"] == ["6930"]


def test_compose_public_url_with_gateway(manager: SessionManager) -> None:
    result = manager._compose_public_url(
        "http://localhost:6080/vnc",
        6930,
        "/vnc.html",
        query_params={"path": "websockify"},
    )

    parsed = urlparse(result)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost:6080"
    assert parsed.path == "/vnc/vnc.html"
    query = parse_qs(parsed.query)
    assert query["path"] == ["vnc/websockify"]
    assert query["target_port"] == ["6930"]


def test_compose_public_url_with_gateway_existing_prefix(manager: SessionManager) -> None:
    result = manager._compose_public_url(
        "http://localhost:6080/vnc",
        6930,
        "/vnc.html",
        query_params={"path": "vnc/websockify"},
    )

    parsed = urlparse(result)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost:6080"
    assert parsed.path == "/vnc/vnc.html"
    query = parse_qs(parsed.query)
    assert query["path"] == ["vnc/websockify"]
    assert query["target_port"] == ["6930"]


def test_compose_public_url_preserves_existing_target(manager: SessionManager) -> None:
    result = manager._compose_public_url(
        "http://localhost:6080/vnc?target_port=1234",
        6930,
        "/websockify",
    )

    assert result == "http://localhost:6080/vnc/websockify?target_port=1234"
