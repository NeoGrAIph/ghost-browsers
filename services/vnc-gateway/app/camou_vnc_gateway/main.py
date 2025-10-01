"""Application entrypoint for the VNC gateway service."""

from __future__ import annotations

from fastapi import FastAPI

from .config import Settings, get_settings
from .dependencies import get_runner_proxy
from .routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application instance."""

    app = FastAPI(title="Ghost Browsers VNC Gateway", version="0.1.0")

    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    app.include_router(router)

    @app.on_event("shutdown")
    async def _shutdown_runner_proxy() -> None:  # pragma: no cover - FastAPI lifecycle hook
        proxy = getattr(get_runner_proxy, "_instance", None)
        if proxy is not None:
            await proxy.aclose()

    return app


app = create_app()


__all__ = ["app", "create_app"]
