from backend.app.api.routes_agents import router as agents_router
from backend.app.api.routes_calls import router as calls_router
from backend.app.api.routes_health import router as health_router

__all__ = ["agents_router", "calls_router", "health_router"]
