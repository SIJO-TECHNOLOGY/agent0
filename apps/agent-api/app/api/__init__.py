"""FastAPI routers."""

from app.api.health import router as health_router
from app.api.mcp_debug import router as mcp_debug_router
from app.api.mcp_tools import router as mcp_tools_router
from app.api.ready import router as ready_router
from app.api.search import router as search_router
from app.api.search_stream import router as search_stream_router

__all__ = [
    "health_router",
    "mcp_debug_router",
    "mcp_tools_router",
    "ready_router",
    "search_router",
    "search_stream_router",
]
