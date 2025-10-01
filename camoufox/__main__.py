"""Command-line interface for the Camoufox stub package.

The real Camoufox distribution exposes a CLI with commands such as
``python -m camoufox path``. Our stub mirrors the subset used in local
checks so developers can validate configuration without the proprietary
binary.

Example:
    >>> import subprocess
    >>> subprocess.check_output(["python", "-m", "camoufox", "path"]).strip()
    b'/usr/bin/camoufox'
"""

from __future__ import annotations

import argparse
import sys

from . import get_path, get_version


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser for supported subcommands."""

    parser = argparse.ArgumentParser(prog="python -m camoufox")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("path", help="Show the expected Camoufox binary path")
    subparsers.add_parser("version", help="Show the stub Camoufox version")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked via ``python -m camoufox``.

    Args:
        argv: Optional list of command-line arguments. When ``None`` the
            arguments are read from :data:`sys.argv`.

    Returns:
        int: Exit status code compatible with shell conventions.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "path":
        print(get_path())
        return 0

    if args.command == "version":
        print(get_version())
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
