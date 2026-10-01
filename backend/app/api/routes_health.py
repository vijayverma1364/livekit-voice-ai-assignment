import datetime
import httpx
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.db.session import get_db

router = APIRouter(tags=["Health"])


@router.get("/health", summary="System Health & Upstream Dependency Check")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Checks operational health of the FastAPI service and its upstream dependencies
    (PostgreSQL database and LiveKit SFU).
    """
    db_status = "disconnected"
    livekit_status = "disconnected"
    is_healthy = True

    # 1. Check PostgreSQL connectivity
    try:
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            db_status = "connected"
    except Exception:
        is_healthy = False
        db_status = "error"

    # 2. Check LiveKit connectivity
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.LIVEKIT_URL}/")
            # LiveKit HTTP returns 200 or 404 (for root) when healthy
            if resp.status_code in (200, 404):
                livekit_status = "connected"
            else:
                livekit_status = f"http_{resp.status_code}"
    except Exception:
        # LiveKit failure affects realtime calling capability
        livekit_status = "unreachable"

    response_data = {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dependencies": {
            "database": db_status,
            "livekit": livekit_status,
        },
        "version": "1.0.0",
    }

    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response_data,
        )

    return response_data
