"""Entrypoint for ``python -m camoufox_runner``."""

from __future__ import annotations

import uvicorn

from .config import load_settings
from .main import create_app


def main() -> None:
    """Load configuration and start the FastAPI app using uvicorn."""

    # Loading settings lazily ensures environment variables set by the runtime
    # (Docker, systemd, etc.) are honoured.
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
