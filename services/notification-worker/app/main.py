"""Entry point: python -m app.main"""

import logging
import os
import signal
import threading
from types import FrameType

import redis

from app import logging_config
from app.config import get_settings
from app.metrics import start_metrics_server
from app.worker import Worker

logger = logging.getLogger(__name__)


def install_signal_handlers(stop: threading.Event) -> None:
    """SIGTERM (Kubernetes stopping the pod) and SIGINT (Ctrl+C) ask the loop to finish."""

    def _handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("shutdown requested", extra={"signal": signal.Signals(signum).name})
        stop.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main() -> None:
    logging_config.configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    settings = get_settings()  # raises at startup if REDIS_URL or HOSTNAME is missing

    stop = threading.Event()
    install_signal_handlers(stop)

    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_timeout_seconds,
        # A blocking XREADGROUP holds the socket open for block_ms, so the read
        # timeout must be longer than that or every idle poll would time out.
        socket_timeout=settings.redis_timeout_seconds + settings.block_ms / 1000,
    )
    server = start_metrics_server(settings.metrics_port)
    worker = Worker(
        client,
        stream=settings.payments_stream,
        group=settings.consumer_group,
        consumer=settings.consumer_name,
        block_ms=settings.block_ms,
        batch_size=settings.batch_size,
        claim_idle_ms=settings.claim_idle_ms,
    )

    logger.info(
        "worker started",
        extra={
            "stream": settings.payments_stream,
            "group": settings.consumer_group,
            "consumer": settings.consumer_name,
            "metrics_port": server.server_port,
        },
    )
    try:
        worker.run(stop)
    finally:
        client.close()
        server.shutdown()
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
