from http.server import HTTPServer

from prometheus_client import Counter, start_http_server

from app.events import INVALID_REASONS

NOTIFICATIONS_SENT = Counter(
    "notifications_sent_total",
    "payment.completed events turned into a notification",
)
EVENTS_INVALID = Counter(
    "events_invalid_total",
    "Stream entries that could not be parsed; acked and dropped",
    ["reason"],
)
REDIS_ERRORS = Counter(
    "redis_errors_total",
    "Redis calls that failed; the worker backs off and retries",
)

# Create every reason at 0, so rate() works from the first scrape.
for _reason in INVALID_REASONS:
    EVENTS_INVALID.labels(_reason)


def start_metrics_server(port: int) -> HTTPServer:
    """Serve /metrics on a side port in a background thread. Port 0 picks a free port."""
    server, _thread = start_http_server(port)
    return server
