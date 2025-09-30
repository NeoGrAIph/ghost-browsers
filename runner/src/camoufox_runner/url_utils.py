"""Helpers for working with user-provided URLs."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_SCHEME_ONLY_PROTOCOLS = {"about", "data", "file", "javascript", "mailto"}


def navigable_start_url(raw_url: str, default_scheme: str = "https") -> str:
    """Return a URL that Playwright can navigate to.

    The control plane forwards the exact string the operator entered, which can
    be a bare hostname like ``example.com``. Browsers require an explicit
    scheme, so we infer a ``https://`` prefix when the value looks like a
    hostname or host/path combination. Relative paths (``/foo`` or
    ``./foo``) are returned untouched so callers can decide how to handle
    them.
    """

    parts = urlsplit(raw_url)
    if parts.scheme and ("://" in raw_url or parts.scheme in _SCHEME_ONLY_PROTOCOLS):
        return raw_url

    alt_source = raw_url if raw_url.startswith("//") else f"//{raw_url}"
    alt_parts = urlsplit(alt_source)
    if alt_parts.netloc and alt_parts.netloc not in {".", ".."}:
        return urlunsplit(
            (default_scheme, alt_parts.netloc, alt_parts.path, alt_parts.query, alt_parts.fragment)
        )

    if not parts.path or parts.path.startswith(("/", ".", "#")):
        return raw_url

    host, separator, remainder = parts.path.partition("/")
    path = f"/{remainder}" if separator else ""
    return urlunsplit((default_scheme, host, path, parts.query, parts.fragment))
