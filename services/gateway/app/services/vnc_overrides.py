"""Utilities for translating runner-provided VNC URLs into public endpoints."""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from core import Runner, SessionVncDetails

LOGGER = logging.getLogger(__name__)


def apply_vnc_overrides(
    runner: Runner,
    details: SessionVncDetails | None,
    *,
    session_id: str,
) -> SessionVncDetails | None:
    """Return VNC details with public overrides applied when configured.

    Args:
        runner: Runner configuration that may expose override templates.
        details: Original VNC descriptor provided by the runner.
        session_id: Identifier of the session for placeholder substitution.

    Returns:
        SessionVncDetails | None: Updated descriptor referencing the shared
        gateway, or the original descriptor when no overrides were applied.

    The beta control-plane exposes ``vnc_http`` and ``vnc_ws`` override
    templates to collapse many internal VNC ports behind a small public proxy.
    Adopting the same behaviour allows the gateway to point UI clients at a
    limited set of ingress endpoints instead of leaking every worker's port
    allocations.
    """

    if details is None:
        return None

    http_source = str(details.http_url) if details.http_url is not None else None
    ws_source = str(details.websocket_url) if details.websocket_url is not None else None

    http_public = _build_public_vnc_url(
        runner.vnc_http_url_template,
        session_id,
        http_source,
        runner_id=runner.id,
        channel="http",
    )
    ws_public = _build_public_vnc_url(
        runner.vnc_ws_url_template,
        session_id,
        ws_source,
        runner_id=runner.id,
        channel="ws",
    )

    if http_public == http_source and ws_public == ws_source:
        return details

    payload: dict[str, str | None] = {
        "http_url": http_public,
        "websocket_url": ws_public,
    }
    merged = details.model_dump(mode="json")
    merged.update({key: value for key, value in payload.items() if value is not None})
    # When an override explicitly removes a channel (returns ``None``) we ensure
    # the key is dropped to avoid keeping stale values from the runner payload.
    if http_public is None:
        merged.pop("http_url", None)
    if ws_public is None:
        merged.pop("websocket_url", None)
    return SessionVncDetails.model_validate(merged)


def _build_public_vnc_url(
    override_template: str | None,
    session_id: str,
    fallback: str | None,
    *,
    runner_id: str,
    channel: str,
) -> str | None:
    """Return a single public VNC URL produced from an override template."""

    if not override_template:
        return fallback
    try:
        formatted = override_template.format(id=session_id)
    except Exception as exc:  # pragma: no cover - defensive guard against bad config
        LOGGER.warning(
            "Invalid %s VNC override on runner %s: %s",
            channel,
            runner_id,
            exc,
        )
        return fallback
    try:
        override_parts = urlparse(formatted)
    except ValueError as exc:  # pragma: no cover - defensive guard against bad config
        LOGGER.warning(
            "Failed to parse %s VNC override on runner %s: %s",
            channel,
            runner_id,
            exc,
        )
        return fallback

    fallback_parts = urlparse(fallback) if fallback else None
    scheme = override_parts.scheme or (fallback_parts.scheme if fallback_parts else "")
    netloc = override_parts.netloc or (fallback_parts.netloc if fallback_parts else "")
    path = _merge_vnc_paths(override_parts.path, fallback_parts.path if fallback_parts else "")

    query_items = parse_qsl(override_parts.query, keep_blank_values=True)
    seen = {key for key, _ in query_items}
    if fallback_parts and fallback_parts.query:
        for key, value in parse_qsl(fallback_parts.query, keep_blank_values=True):
            if key not in seen:
                query_items.append((key, value))
                seen.add(key)
    query = urlencode(query_items)

    return urlunparse((scheme, netloc, path or "/", "", query, ""))


def _merge_vnc_paths(override_path: str, fallback_path: str) -> str:
    """Merge override and fallback paths similar to the beta implementation."""

    original_override = override_path or ""
    base = original_override.rstrip("/")
    fallback = fallback_path or ""

    if not fallback or fallback == "/":
        return base or fallback or "/"

    base_segments = [segment for segment in base.split("/") if segment]
    fallback_segments = [segment for segment in fallback.split("/") if segment]

    if not base_segments:
        if not fallback_segments:
            return "/" if (original_override.startswith("/") or fallback.startswith("/")) else ""
        prefix = "/" if (original_override.startswith("/") or fallback.startswith("/")) else ""
        return f"{prefix}{'/'.join(fallback_segments)}"

    if fallback_segments and len(fallback_segments) >= len(base_segments):
        if fallback_segments[-len(base_segments):] == base_segments:
            leading_slash = original_override.startswith("/") or fallback.startswith("/")
            joined_base = "/".join(base_segments)
            return f"/{joined_base}" if leading_slash else joined_base

    common = 0
    limit = min(len(base_segments), len(fallback_segments))
    while common < limit and base_segments[common] == fallback_segments[common]:
        common += 1

    merged_segments = base_segments + fallback_segments[common:]

    if not merged_segments:
        return "/"

    leading_slash = original_override.startswith("/") or fallback.startswith("/")
    joined = "/".join(merged_segments)
    return f"/{joined}" if leading_slash else joined


__all__ = ["apply_vnc_overrides"]
