from camofleet_vnc_gateway.main import (
    _build_upstream_url,
    _join_paths,
    _normalise_client_path,
)


def test_build_upstream_url_with_prefix() -> None:
    result = _build_upstream_url(
        scheme="http",
        host="runner",
        port=6901,
        prefix="/vnc",
        path_suffix="/vnc.html",
        query="path=websockify",
    )

    assert result == "http://runner:6901/vnc/vnc.html?path=websockify"


def test_join_paths_handles_root() -> None:
    assert _join_paths("", "/websockify") == "/websockify"
    assert _join_paths("/prefix", "/") == "/prefix"


def test_normalise_client_path_preserves_static_assets() -> None:
    assert _normalise_client_path("/core/rfb.js") == "/core/rfb.js"
    assert _normalise_client_path("/") == "/"


def test_normalise_client_path_strips_session_segment() -> None:
    uuid_segment = "ea4100ce-15a6-44b3-ab81-b5a180159653"
    assert _normalise_client_path(f"/{uuid_segment}/vnc.html") == "/vnc.html"
    assert (
        _normalise_client_path(f"/{uuid_segment}/core/rfb.js")
        == "/core/rfb.js"
    )
