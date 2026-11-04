from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, str]:
    """Readiness: dependencies needed to serve traffic are reachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "down"}
    return {"status": "ready", "database": "up"}
