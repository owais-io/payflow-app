from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

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


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
