"""Minimal smoke test for verifying Camoufox usability inside the worker image."""

from __future__ import annotations

import sys

from camoufox.errors import CamoufoxNotInstalled
from camoufox.sync_api import Camoufox


def main() -> int:
    """Open example.com with Camoufox to validate rendering and report the page title.

    Returns:
        int: Exit code compatible with :func:`sys.exit`.
    """

    try:
        with Camoufox(headless="virtual", geoip=True) as browser:
            page = browser.new_page()
            page.goto("https://example.com")
            print("Title:", page.title())
    except CamoufoxNotInstalled:
        print(
            "Camoufox binaries are not installed. Run `python -m camoufox fetch` "
            "before executing the worker smoke test.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - manual smoke helper
    raise SystemExit(main())
