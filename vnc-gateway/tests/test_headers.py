from camofleet_vnc_gateway.main import _select_upstream_headers


def test_select_upstream_headers_filters() -> None:
    headers = [
        ("Origin", "http://localhost"),
        ("Host", "example"),
        ("User-Agent", "pytest"),
        ("Sec-WebSocket-Extensions", "permessage-deflate"),
    ]

    result = _select_upstream_headers(headers)

    assert ("Origin", "http://localhost") in result
    assert ("User-Agent", "pytest") in result
    assert all(key.lower() != "host" for key, _ in result)
