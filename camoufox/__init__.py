"""Utilities and sync helpers for the local Camoufox stub.

This lightweight module mimics the public surface that the real
`camoufox` distribution exposes so that unit tests for the gateway and
runner services can be executed without downloading the browser
runtime. The stub focuses on providing deterministic answers about the
Camoufox binary location and version string, while still offering a
minimal synchronous context manager used by smoke tests.

Example:
    >>> from camoufox import get_path, get_version
    >>> str(get_path())
    '/usr/bin/camoufox'
    >>> get_version()
    '0.0.0-stub'
"""

from __future__ import annotations

from pathlib import Path

_CAMOUFOX_PATH = Path("/usr/bin/camoufox")
_CAMOUFOX_VERSION = "0.0.0-stub"


def get_path() -> Path:
    """Return the expected filesystem path of the Camoufox binary.

    The real runtime ships an executable that is later used by the
    session runner. Our stub keeps the same contract so configuration
    validators inside the services can continue working.

    Returns:
        Path: Absolute path where the Camoufox binary is expected.

    Example:
        >>> from camoufox import get_path
        >>> get_path().as_posix()
        '/usr/bin/camoufox'
    """

    return _CAMOUFOX_PATH


def get_version() -> str:
    """Return a deterministic semantic version string for the stub.

    Returns:
        str: The placeholder version reported by the stub.

    Example:
        >>> from camoufox import get_version
        >>> get_version()
        '0.0.0-stub'
    """

    return _CAMOUFOX_VERSION


from .sync_api import Camoufox  # noqa: E402

__all__ = ["Camoufox", "get_path", "get_version"]
