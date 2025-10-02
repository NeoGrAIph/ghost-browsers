"""Minimal smoke test for validating the Camoufox SDK integration."""

from __future__ import annotations

import sys

from camoufox.errors import CamoufoxNotInstalled
from camoufox.sync_api import Camoufox


def main() -> int:
    """Launch Camoufox and print the title of example.com.

    Returns:
        int: Process exit code compatible with ``sys.exit``.
    """

    try:
        # headless="virtual" активирует Xvfb (нужен пакет xvfb)
        with Camoufox(headless="virtual", geoip=True) as browser:
            page = browser.new_page()
            page.goto("https://example.com")
            print("Title:", page.title())
    except CamoufoxNotInstalled as exc:
        print(
            "Camoufox binaries are not installed. Run `python -m camoufox fetch` "
            "before executing the smoke test.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - manual smoke helper
    raise SystemExit(main())
