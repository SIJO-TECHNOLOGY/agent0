"""FastAPI routers."""

from app.api.health import router as health_router
from app.api.ready import router as ready_router
from app.api.search import router as search_router

__all__ = ["health_router", "ready_router", "search_router"]
