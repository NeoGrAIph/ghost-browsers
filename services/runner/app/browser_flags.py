"""Utilities for normalising and merging Camoufox browser flags."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = [
    "merge_browser_flags",
    "normalise_browser_flags",
    "requires_additional_flags",
]


def normalise_browser_flags(flags: Mapping[str, Any] | None) -> dict[str, str]:
    """Return a sanitized mapping of browser flag names to string values.

    Args:
        flags: Raw mapping of flag names to arbitrary values. Non-mapping inputs
            or keys with empty names are ignored. ``None`` returns an empty
            dictionary.

    Returns:
        dict[str, str]: Normalised mapping safe to inject into environment
            variables for the Camoufox launcher. Boolean values are converted to
            ``"1"``/``"0"`` to align with Mozilla flag expectations; other
            values are stringified via :func:`str`.

    Example:
        >>> normalise_browser_flags({"MOZ_DISABLE_HTTP3": True})
        {'MOZ_DISABLE_HTTP3': '1'}
    """

    if not flags:
        return {}
    normalised: dict[str, str] = {}
    for key, value in flags.items():
        if not isinstance(key, str):
            continue
        name = key.strip()
        if not name or value is None:
            continue
        if isinstance(value, bool):
            normalised[name] = "1" if value else "0"
        else:
            normalised[name] = str(value)
    return normalised


def merge_browser_flags(*sources: Mapping[str, Any] | None) -> dict[str, str]:
    """Combine ``sources`` into a single mapping of browser flags.

    Later sources win on key collisions which mirrors how worker-provided flags
    should override defaults coming from the runner configuration.

    Args:
        *sources: Optional mappings describing browser flags.

    Returns:
        dict[str, str]: Combined mapping with duplicate keys resolved in favour
            of the last source.

    Example:
        >>> merge_browser_flags({"MOZ_DISABLE_HTTP3": "1"}, {"EXTRA": "flag"})
        {'MOZ_DISABLE_HTTP3': '1', 'EXTRA': 'flag'}
    """

    merged: dict[str, str] = {}
    for source in sources:
        if not source:
            continue
        merged.update(normalise_browser_flags(source))
    return merged


def requires_additional_flags(
    requested: Mapping[str, str], baseline: Mapping[str, str]
) -> bool:
    """Return ``True`` when ``requested`` contains values outside ``baseline``.

    The helper is used to decide whether a session can be served by a warm
    workstation (which only knows about baseline flags) or requires a bespoke
    cold launch.

    Args:
        requested: Normalised mapping of flags requested for a session.
        baseline: Normalised mapping of flags pre-applied by the warm pool.

    Returns:
        bool: ``True`` when ``requested`` contains keys absent from ``baseline``
            or values that differ from it.

    Example:
        >>> requires_additional_flags({"EXTRA": "1"}, {"MOZ_DISABLE_HTTP3": "1"})
        True
    """

    for key, value in requested.items():
        if baseline.get(key) != value:
            return True
    return False
