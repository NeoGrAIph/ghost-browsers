"""REST and realtime routers exposed by the gateway."""

from .events import router as events_router
from .runners import router as runners_router
from .sessions import router as sessions_router
from .workstations import router as workstations_router

__all__ = [
    "sessions_router",
    "runners_router",
    "events_router",
    "workstations_router",
]
