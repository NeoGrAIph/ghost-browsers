"""Command line interface delegating to the official Camoufox SDK."""

from __future__ import annotations

from types import ModuleType

from . import _load_sdk_module


_CLI_MODULE: ModuleType = _load_sdk_module("__main__")
"""Reference to the upstream CLI implementation shipped with the SDK."""

cli = _CLI_MODULE.cli
fetch = _CLI_MODULE.fetch
path = _CLI_MODULE.path
version = _CLI_MODULE.version

__all__ = ["cli", "fetch", "path", "version", "main"]


def main() -> None:
    """Execute the official Camoufox command line interface.

    Example:
        >>> # main()  # doctest: +SKIP
    """

    cli()


if __name__ == "__main__":  # pragma: no cover - manual invocation helper
    main()
