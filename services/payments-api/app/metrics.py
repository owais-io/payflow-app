import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

logger = logging.getLogger(__name__)
QUIET_PATHS = {"/healthz", "/readyz", "/metrics"}

# --- HTTP metrics (same as accounts-api) ---

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

# --- Business metrics (1.3.4) ---

FAILURE_REASONS = (
    "same_account",
    "account_not_found",
    "accounts_unavailable",
    "insufficient_funds",
)

PAYMENTS = Counter("payments_total", "Completed transfers")
PAYMENTS_FAILED = Counter(
    "payments_failed_total",
    "Transfers rejected after the request body was valid",
    ["reason"],
)
PAYMENT_AMOUNT = Histogram(
    "payment_amount",
    "Amount of completed transfers, in PKR",
    buckets=(100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000),
)
EVENTS_PUBLISH_FAILED = Counter(
    "events_publish_failed_total",
    "payment.completed events that could not be published to Redis",
)

# Create every reason at 0, so rate() works from the first scrape and
# dashboards show a flat line instead of "no data".
for _reason in FAILURE_REASONS:
    PAYMENTS_FAILED.labels(_reason)

router = APIRouter()


async def track_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    status_code = 500  # if the handler raises, the request counts as a 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        duration = time.perf_counter() - start
        if path not in QUIET_PATHS:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": path,
                    "status": status_code,
                    "duration_ms": round(duration * 1000, 1),
                },
            )
        REQUESTS.labels(request.method, path, str(status_code)).inc()
        LATENCY.labels(request.method, path).observe(duration)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
