import redis
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, str]:
    """Readiness: can this pod serve payments?

    PostgreSQL is a hard dependency: without it no transfer can happen, so 503.
    Redis is a soft dependency: transfers still succeed without it (the event is
    lost and counted), so it is reported but never makes the pod unready.
    accounts-api is not checked: if it is down, every payments pod would go
    unready at once and the failure would spread instead of returning a clear 503.
    """
    result = {"status": "ready", "database": "up", "redis": "up"}

    try:
        request.app.state.redis.ping()
    except redis.RedisError:
        result["redis"] = "down"

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        result["status"] = "unavailable"
        result["database"] = "down"

    return result
