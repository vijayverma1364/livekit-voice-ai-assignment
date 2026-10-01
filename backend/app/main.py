import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes_agents import router as agents_router
from backend.app.api.routes_calls import router as calls_router
from backend.app.api.routes_health import router as health_router
from backend.app.core.config import settings
from backend.app.db.seed import seed_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure default Acme Support Agent is seeded
    logger.info("Initializing FastAPI Backend Control Plane...")
    try:
        await seed_agent()
    except Exception as e:
        logger.warning("Could not run initial agent seeding: %s", e)
    yield
    logger.info("Shutting down FastAPI Backend...")


app = FastAPI(
    title="Supervised Voice AI Agent Control Plane",
    description="Stateless REST API managing agent configurations, call lifecycles, LiveKit room orchestration, and post-call analytics.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
origins = set([origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()])
origins.update([
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:8000",
])

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(origins),
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(health_router)
app.include_router(agents_router)
app.include_router(calls_router)


from pathlib import Path
from fastapi import Request
from fastapi.responses import HTMLResponse

PORTAL_HTML_PATH = Path(__file__).parent / "templates" / "portal.html"


@app.get("/", include_in_schema=False)
async def root(request: Request):
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        return {
            "service": "Supervised Voice AI Agent Control Plane",
            "docs": "/docs",
            "health": "/health",
            "portal": "http://localhost:8000/",
        }
    if PORTAL_HTML_PATH.exists():
        return HTMLResponse(content=PORTAL_HTML_PATH.read_text(encoding="utf-8"))
    return {
        "service": "Supervised Voice AI Agent Control Plane",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/portal", response_class=HTMLResponse, include_in_schema=False)
async def portal_page():
    if PORTAL_HTML_PATH.exists():
        return HTMLResponse(content=PORTAL_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Portal template not found</h1>", status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=True,
    )
