"""Tests for target_port resolution helpers."""

from camofleet_vnc_gateway.main import (
    TARGET_PORT_COOKIE,
    _extract_port_from_referer,
    _parse_cookie_header,
    _select_target_port,
)


def test_select_target_port_prefers_query() -> None:
    port, source = _select_target_port(
        query_value="6910",
        referer="http://localhost/vnc/vnc.html?target_port=6920",
        cookies={TARGET_PORT_COOKIE: "6930"},
    )
    assert port == "6910"
    assert source == "query"


def test_select_target_port_prefers_referer_over_cookie() -> None:
    port, source = _select_target_port(
        query_value=None,
        referer="http://localhost/vnc/vnc.html?target_port=6920",
        cookies={TARGET_PORT_COOKIE: "6930"},
    )
    assert port == "6920"
    assert source == "referer"


def test_select_target_port_uses_cookie_when_needed() -> None:
    port, source = _select_target_port(
        query_value=None,
        referer="http://localhost/vnc/vnc.html",
        cookies={TARGET_PORT_COOKIE: "6930"},
    )
    assert port == "6930"
    assert source == "cookie"


def test_select_target_port_handles_missing_values() -> None:
    port, source = _select_target_port(query_value=None, referer=None, cookies={})
    assert port is None
    assert source is None


def test_extract_port_from_referer_parses_query() -> None:
    referer = "http://localhost/vnc/vnc.html?foo=1&target_port=6945"
    assert _extract_port_from_referer(referer) == "6945"


def test_extract_port_from_referer_missing_value() -> None:
    assert _extract_port_from_referer(None) is None
    assert _extract_port_from_referer("http://localhost/vnc/vnc.html") is None


def test_parse_cookie_header_extracts_values() -> None:
    header = "a=1; vnc-target-port=6950; other=value"
    cookies = _parse_cookie_header(header)
    assert cookies["a"] == "1"
    assert cookies[TARGET_PORT_COOKIE] == "6950"


def test_parse_cookie_header_handles_invalid_header() -> None:
    cookies = _parse_cookie_header("invalid-cookie\nvalue")
    assert cookies == {}
