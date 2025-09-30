"""Entrypoint for ``python -m camofleet_control``."""

from __future__ import annotations

import uvicorn

from .config import load_settings
from .main import create_app


def main() -> None:
    """Resolve settings and start the uvicorn server."""

    # Delaying configuration until runtime ensures environment variables set by
    # the launcher are taken into account.
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
