import json
from collections.abc import Callable
from uuid import uuid4

import fakeredis
import pytest

from app.worker import Worker

STREAM = "payflow:payments"
GROUP = "notification-workers"


def make_event(**overrides) -> dict:
    """An event exactly as payments-api publishes it (see payments-api/app/events.py)."""
    event = {
        "event_id": str(uuid4()),
        "event_type": "payment.completed",
        "version": 1,
        "occurred_at": "2026-11-06T14:05:00Z",
        "data": {
            "payment_id": str(uuid4()),
            "from_account_id": str(uuid4()),
            "to_account_id": str(uuid4()),
            "amount": "250.00",
            "currency": "PKR",
        },
    }
    event.update(overrides)
    return event


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    # decode_responses=True, as in app/main.py
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def publish(redis_client) -> Callable[..., str]:
    """XADD one entry the way payments-api does. Pass raw fields to send something broken."""

    def _publish(event: dict | None = None, fields: dict | None = None) -> str:
        if fields is None:
            fields = {"payload": json.dumps(event or make_event())}
        return redis_client.xadd(STREAM, fields)

    return _publish


@pytest.fixture
def make_worker(redis_client) -> Callable[..., Worker]:
    def _make(consumer: str = "worker-a", **kwargs) -> Worker:
        kwargs.setdefault("block_ms", 1)  # keep tests fast
        return Worker(redis_client, stream=STREAM, group=GROUP, consumer=consumer, **kwargs)

    return _make


def pending_count(client) -> int:
    return client.xpending(STREAM, GROUP)["pending"]
