"""Minimal smoke test for verifying Camoufox usability inside the worker image."""

from camoufox.sync_api import Camoufox


def main() -> None:
    """Open example.com with Camoufox to validate rendering and report the page title."""
    with Camoufox(headless="virtual", geoip=True) as browser:
        page = browser.new_page()
        page.goto("https://example.com")
        print("Title:", page.title())


if __name__ == "__main__":
    main()
