"""Synchronous Camoufox facade used by the smoke test harness.

The real Camoufox distribution exposes a synchronous API that behaves
like a minimal Playwright wrapper. For unit testing we only require a
context manager that tracks the configured binary path and version
string, returning lightweight page objects that record navigation
requests without performing any I/O.

Example:
    >>> from camoufox.sync_api import Camoufox
    >>> with Camoufox() as browser:
    ...     page = browser.new_page()
    ...     page.goto("https://example.com")
    ...     page.title()
    'Camoufox Stub Page'
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import get_path, get_version


@dataclass
class _StubPage:
    """Represent a navigated page for the Camoufox stub.

    The object only stores the last requested URL and exposes an
    extremely small subset of the Playwright `Page` interface that is
    referenced in our smoke test.

    Attributes:
        url: The last URL that the caller navigated to, if any.
        title_text: Title string returned by :meth:`title`.
    """

    url: Optional[str] = None
    title_text: str = "Camoufox Stub Page"

    def goto(self, url: str) -> None:
        """Record a navigation request.

        Args:
            url: Absolute or relative URL requested by the caller.

        Example:
            >>> page = _StubPage()
            >>> page.goto("https://example.com")
            >>> page.url
            'https://example.com'
        """

        self.url = url

    def title(self) -> str:
        """Return the stored title for the stub page."""

        return self.title_text


class Camoufox:
    """Minimal synchronous facade compatible with smoke tests.

    Args:
        headless: Placeholder parameter to mirror the real API.
        geoip: Placeholder flag kept for compatibility with production
            code; the stub ignores it.
        binary_path: Optional override for the Camoufox executable path.
        version: Optional override for the version string.
        **kwargs: Accept and ignore any other keyword arguments so the
            stub remains forward compatible with additional flags.

    Example:
        >>> with Camoufox(binary_path="/tmp/camoufox", version="1.2.3") as browser:
        ...     browser.path()
        PosixPath('/tmp/camoufox')
        >>> Camoufox().version()
        '0.0.0-stub'
    """

    def __init__(
        self,
        *,
        headless: str | bool | None = None,
        geoip: bool | None = None,
        binary_path: str | Path | None = None,
        version: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._headless = headless
        self._geoip = geoip
        self._binary_path = Path(binary_path) if binary_path else get_path()
        self._version = version or get_version()
        self._last_page: Optional[_StubPage] = None
        self._extra_args = dict(kwargs)

    def __enter__(self) -> "Camoufox":
        """Return the stub browser instance without side effects."""

        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
        """Release resources and propagate exceptions.

        The stub has no external resources; returning ``False`` allows
        exceptions raised inside the context to bubble up as expected.
        """

        self._last_page = None
        return False

    # Public API -----------------------------------------------------
    def new_page(self, **kwargs: Any) -> _StubPage:
        """Create a new stub page and store it as the most recent page.

        Args:
            **kwargs: Additional flags ignored by the stub. They are
                accepted to mimic the behaviour of the production
                bindings.

        Returns:
            _StubPage: Page object that records navigation requests.
        """

        self._last_page = _StubPage()
        return self._last_page

    def path(self) -> Path:
        """Return the configured Camoufox binary path."""

        return self._binary_path

    def version(self) -> str:
        """Return the Camoufox version string associated with the stub."""

        return self._version

    # Diagnostic helpers ---------------------------------------------
    def last_page(self) -> Optional[_StubPage]:
        """Expose the most recent page for assertions in tests."""

        return self._last_page

    def extra_args(self) -> dict[str, Any]:
        """Return a shallow copy of unused keyword arguments."""

        return dict(self._extra_args)
